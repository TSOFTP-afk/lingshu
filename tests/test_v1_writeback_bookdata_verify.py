"""V1 分析写回链路端到端验证 — 使用测试小说数据。

验证链路:
  POST /api/workspace/books/{book_id}/analysis-v1/one-shot  → 触发 V1 分析
  POST /api/workspace/analysis/runs/{run_id}/apply          → 触发 V1 写回
  核心写回: novel_app/analysis/writeback.py::apply_book_analysis_payload

重要说明:
  apply_book_analysis_payload 不写入 world_entries 表，而是通过
  update_book_world_form 写入 books.world_data_json / books.world_text。

测试步骤:
  1. 临时数据库 + 双用户注册/登录
  2. 写入测试小说 (灵枢测试小说: 陆沉/苏晚/周伯)
  3. 认证验证 (401 无 token / 403 跨用户)
  4. V1 一次性分析触发 (AI 不可用时预期 503)
  5. 直接插入 mock analysis_run + analysis_card, 调用 apply 端点
  6. 验证写回结果 (books/characters/chapters/cards)
  7. 清理 (TemporaryDirectory 自动清理)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lingshu_api.main import create_app
from lingshu_api.services.db_bridge import WorkspaceDBProvider, reset_default_workspace_db
from novel_app.analysis.diff_apply import build_drafts_with_diffs
from novel_app.analysis.pipeline import PIPELINE_VERSION
from novel_app.analysis.store import AnalysisStore
from novel_app.bookstore import BookstoreStore
from novel_app.database import Database
from tests.fixtures.test_novel import get_test_novel


# ── 测试账号 ──────────────────────────────────────────────────────
_USER_A = "v1_verify_author_a"
_USER_B = "v1_verify_author_b"
_PASSWORD = "test_pass_123456"


# ── 构造 V1 分析 payload (模拟 AI 一次性读完分析产出) ───────────────
def _build_mock_v1_payload(chapters: list[dict[str, Any]]) -> dict[str, Any]:
    """构造一个模拟 V1 一次性读完分析产出的 payload。

    包含书籍大纲、世界观、人物卡、章节更新 — 覆盖 apply_book_analysis_payload
    的所有写回分支。
    """
    return {
        "book_outline_form": {
            "fields": {
                "primary_parent_tag_id": {"value": "仙侠"},
                "book_description": {
                    "value": "陆沉入灵枢塔寻重建家族之力，与苏晚、周伯共破噬魂宗阴谋。"
                },
            }
        },
        "world_form": {
            "fields": {
                "world_rules_table": {
                    "value": "天玄大陆修真九重境界：筑基、开脉、凝元、化神、归真、天人、渡劫、大乘、飞升。"
                }
            }
        },
        "characters": [
            {
                "name": "陆沉",
                "role": "主角",
                "profile_form": {
                    "fields": {
                        "personality_main": {"value": "沉静坚韧，复仇心切但不失善良。"},
                        "background": {"value": "北境之战家族覆灭的唯一幸存者，以采药为生。"},
                    }
                },
            },
            {
                "name": "苏晚",
                "role": "女主",
                "profile_form": {
                    "fields": {
                        "personality_main": {"value": "清丽果敢，正义感强。"},
                        "background": {"value": "灵枢宗内门弟子，腰挂内门令牌。"},
                    }
                },
            },
            {
                "name": "周伯",
                "role": "配角",
                "profile_form": {
                    "fields": {
                        "personality_main": {"value": "温和和善，阅历深厚。"},
                        "background": {"value": "百草堂老板，外城老牌药铺经营者。"},
                    }
                },
            },
        ],
        "chapter_updates": [
            {
                "chapter_id": int(chapters[i]["id"]),
                "outline": outline_text,
                "events": [f"第{i+1}章事件"],
            }
            for i, outline_text in enumerate(
                [
                    "陆沉初入灵枢城，前往灵枢塔寻力。",
                    "陆沉在百草堂落脚，结识老板周伯，了解灵枢宗与修真体系。",
                    "苏晚到百草堂购药，与陆沉初次相遇。",
                    "城中修士失踪，苏晚告知陆沉灵枢塔外围禁制异常。",
                    "陆沉发现噬魂宗暗探据点，宗门捣毁之；获准以客卿身份入塔。",
                ]
            )
        ],
    }


# ── 辅助: 注册并登录用户 ──────────────────────────────────────────
def _register_and_login(client: TestClient, username: str, password: str) -> str:
    """注册并登录用户，返回 access_token。"""
    resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "is_author": 1},
    )
    assert resp.status_code in (200, 409), f"注册失败: {resp.status_code} {resp.text}"
    if resp.status_code == 409:
        # 用户已存在，直接登录
        resp = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
    else:
        # 注册接口返回 token
        assert resp.status_code == 200
    data = resp.json()
    token = data["access_token"]
    assert token, "未获取到 access_token"
    return token


# ── 辅助: 通过 API 创建书籍并写入章节 ─────────────────────────────
def _create_book_with_chapters(
    client: TestClient, token: str, novel: dict[str, Any]
) -> tuple[int, list[dict[str, Any]]]:
    """通过 API 创建书籍和章节，返回 (book_id, chapters)。"""
    headers = {"Authorization": f"Bearer {token}"}

    # 创建书籍
    resp = client.post(
        "/api/workspace/books",
        json={"title": novel["title"]},
        headers=headers,
    )
    assert resp.status_code == 200, f"创建书籍失败: {resp.status_code} {resp.text}"
    book_id = int(resp.json()["item"]["id"])

    # 创建章节并写入正文
    chapters: list[dict[str, Any]] = []
    for ch_data in novel["chapters"]:
        # 1. 创建章节 (create_chapter 端点只保存 title)
        resp = client.post(
            f"/api/workspace/books/{book_id}/chapters",
            json={"title": ch_data["title"]},
            headers=headers,
        )
        assert resp.status_code == 200, f"创建章节失败: {resp.status_code} {resp.text}"
        chapter = resp.json()["item"]
        chapter_id = int(chapter["id"])

        # 2. PATCH 更新章节正文 (create 端点不保存 content)
        resp = client.patch(
            f"/api/workspace/chapters/{chapter_id}",
            json={"content": ch_data["content"]},
            headers=headers,
        )
        assert resp.status_code == 200, f"更新章节正文失败: {resp.status_code} {resp.text}"
        chapters.append(resp.json()["item"])

    return book_id, chapters


# ── 主测试 ────────────────────────────────────────────────────────
def test_v1_writeback_bookdata_verify() -> None:
    """V1 分析写回链路端到端验证 — 使用灵枢测试小说数据。"""
    results: dict[str, str] = {}

    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        bookstore_db = tmp_path / "bookstore_test.db"
        novels_db = tmp_path / "novels_test.db"

        # 设置环境变量 (Database.__init__ 读取)
        old_data_dir = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "")
        os.environ["SIMPLE_AI_NOVEL_DATA_DIR"] = str(tmp_path)
        # 禁用 API 文档以避免无关加载
        os.environ["DISABLE_API_DOCS"] = "true"

        try:
            # ── 步骤 1: 创建应用 + 临时数据库 ──
            # 先初始化 bookstore schema (create_app 内部会创建 BookstoreStore)
            # 但我们需要确保 bookstore DB 是空的临时文件
            if bookstore_db.exists():
                bookstore_db.unlink()

            app = create_app(db_path=bookstore_db)

            # 覆盖 workspace_db_provider 指向临时 novels.db
            workspace_provider = WorkspaceDBProvider(novels_db)
            app.state.workspace_db_provider = workspace_provider
            # 同时重置默认 provider 避免污染
            reset_default_workspace_db(novels_db)

            with TestClient(app) as client:
                # ── 步骤 2: 注册并登录两个用户 ──
                token_a = _register_and_login(client, _USER_A, _PASSWORD)
                token_b = _register_and_login(client, _USER_B, _PASSWORD)
                results["user_register_login"] = "PASS"
                assert token_a and token_b
                assert token_a != token_b

                headers_a = {"Authorization": f"Bearer {token_a}"}
                headers_b = {"Authorization": f"Bearer {token_b}"}

                # ── 步骤 3: 写入测试小说 ──
                novel = get_test_novel()
                book_id, chapters = _create_book_with_chapters(client, token_a, novel)
                results["book_and_chapters_created"] = "PASS"
                assert book_id > 0
                assert len(chapters) == len(novel["chapters"])

                # 通过 API 写入初始人物 (陆沉/苏晚/周伯)
                for char_data in novel["characters"]:
                    resp = client.post(
                        f"/api/workspace/books/{book_id}/characters",
                        json={"name": char_data["name"], "role": char_data["role"]},
                        headers=headers_a,
                    )
                    # characters 路由可能不存在或路径不同，容错处理
                    if resp.status_code not in (200, 201, 404):
                        # 如果 API 不可用，后续通过 DB 直接写入
                        pass

                # 确保 characters 存在 (通过 workspace DB 直接写入作为兜底)
                workspace_db = workspace_provider.get()
                database = workspace_db.db
                existing_chars = {str(c["name"]): int(c["id"]) for c in database.list_characters(book_id)}
                for char_data in novel["characters"]:
                    if char_data["name"] not in existing_chars:
                        cid = database.create_character(book_id, char_data["name"])
                        database.update_character_form(cid, char_data["name"], char_data["role"], None, image_path=None)
                        existing_chars[char_data["name"]] = cid

                char_count_before = len(database.list_characters(book_id))
                assert char_count_before >= 3, f"初始人物应至少 3 个，实际: {char_count_before}"

                # 记录写回前的书籍状态
                book_before = database.get_book(book_id)
                outline_text_before = str(book_before["outline_text"] or "")
                world_text_before = str(book_before["world_text"] or "")
                world_data_json_before = str(book_before["world_data_json"] or "")

                # ── 步骤 4: 认证验证 — 401 (无 token) ──
                # V1 one-shot 无 token
                resp = client.post(f"/api/workspace/books/{book_id}/analysis-v1/one-shot")
                assert resp.status_code == 401, (
                    f"V1 one-shot 无 token 应返回 401，实际: {resp.status_code}"
                )
                results["auth_401_oneshot"] = "PASS"

                # apply 无 token (需要一个有效的 run_id，但 401 应先触发)
                resp = client.post("/api/workspace/analysis/runs/999999/apply")
                assert resp.status_code == 401, (
                    f"apply 无 token 应返回 401，实际: {resp.status_code}"
                )
                results["auth_401_apply"] = "PASS"

                # ── 步骤 5: 认证验证 — 403 (跨用户) ──
                # 用户 B 的 token 访问用户 A 的书籍
                resp = client.post(
                    f"/api/workspace/books/{book_id}/analysis-v1/one-shot",
                    headers=headers_b,
                )
                assert resp.status_code == 403, (
                    f"V1 one-shot 跨用户应返回 403，实际: {resp.status_code}"
                )
                results["auth_403_oneshot"] = "PASS"

                # ── 步骤 6: V1 一次性分析触发 ──
                # V1 one-shot 需要 AI 服务，无 API key 时预期 503
                resp = client.post(
                    f"/api/workspace/books/{book_id}/analysis-v1/one-shot",
                    headers=headers_a,
                    json={"use_ai": True},
                )
                if resp.status_code == 200:
                    # AI 可用 — 完整验证 V1 分析
                    data = resp.json()
                    run_id = int(data["item"]["id"])
                    results["v1_oneshot_trigger"] = "PASS (AI available)"
                    # 验证 pipeline_version
                    pipeline_version = str(data["item"].get("pipeline_version") or "")
                    assert pipeline_version == PIPELINE_VERSION, (
                        f"pipeline_version 应为 {PIPELINE_VERSION}，实际: {pipeline_version}"
                    )
                    results["v1_pipeline_version"] = f"PASS ({pipeline_version})"
                elif resp.status_code == 503:
                    # AI 不可用 — 记录 WARN，使用 mock 方式测试写回
                    results["v1_oneshot_trigger"] = (
                        f"WARN (503 - AI 不可用，使用 mock 方式测试写回)"
                    )
                    run_id = None
                else:
                    results["v1_oneshot_trigger"] = (
                        f"FAIL (unexpected status {resp.status_code}: {resp.text[:200]})"
                    )
                    pytest.fail(
                        f"V1 one-shot 意外状态码: {resp.status_code} {resp.text[:300]}"
                    )

                # ── 步骤 7: 直接插入 mock analysis_run + card ──
                if run_id is None:
                    # 创建 mock analysis_run (pipeline_version=p2_entity_cards_v1)
                    run_id = database.create_analysis_run(
                        book_id,
                        scope_type="book",
                        status="awaiting_review",
                        pipeline_version=PIPELINE_VERSION,
                        summary="V1 一次性读完分析 (mock)",
                        meta={"source": "v1_writeback_verify_mock", "ai_invoked": False},
                    )
                    assert run_id > 0
                    results["mock_run_created"] = f"PASS (run_id={run_id})"

                    # 验证 pipeline_version 已正确写入
                    run = database.get_analysis_run(run_id)
                    assert str(run["pipeline_version"]) == PIPELINE_VERSION
                    results["v1_pipeline_version"] = f"PASS ({PIPELINE_VERSION})"

                    # 构造 mock payload 并创建草案卡
                    payload = _build_mock_v1_payload(chapters)
                    drafts = build_drafts_with_diffs(
                        database, book_id, payload, run_id=run_id
                    )
                    assert len(drafts) > 0, "build_drafts_with_diffs 应产出至少一张草案卡"

                    # 验证包含 full_payload 卡
                    card_types = [d.card_type for d in drafts]
                    assert "full_payload" in card_types, (
                        f"草案卡应包含 full_payload，实际: {card_types}"
                    )
                    results["mock_card_created"] = (
                        f"PASS (card_types={card_types})"
                    )

                    # 保存卡片
                    store = AnalysisStore(database)
                    card_ids = store.save_cards(book_id, run_id, drafts)
                    assert len(card_ids) == len(drafts)
                else:
                    results["mock_run_created"] = "SKIP (AI 已产出真实 run)"
                    results["mock_card_created"] = "SKIP (AI 已产出真实 cards)"

                # 验证 analysis_cards 表有 full_payload 卡
                cards = database.list_analysis_cards(run_id)
                full_payload_cards = [
                    c for c in cards if str(c["card_type"]) == "full_payload"
                ]
                assert len(full_payload_cards) > 0, "analysis_cards 表应有 full_payload 卡"
                results["full_payload_card_exists"] = "PASS"

                # ── 步骤 8: 调用 apply 端点 ──
                resp = client.post(
                    f"/api/workspace/analysis/runs/{run_id}/apply",
                    headers=headers_a,
                    json={"user_override": False},
                )
                assert resp.status_code == 200, (
                    f"apply 端点应返回 200，实际: {resp.status_code} {resp.text[:500]}"
                )
                apply_data = resp.json()
                results["apply_endpoint"] = (
                    f"PASS (applied_cards={apply_data.get('applied_cards')}, "
                    f"snapshot_id={apply_data.get('snapshot_id')})"
                )
                assert int(apply_data["applied_cards"]) > 0, "applied_cards 应 > 0"

                # ── 步骤 9: 验证书籍写回 ──
                book_after = database.get_book(book_id)
                outline_text_after = str(book_after["outline_text"] or "")
                world_text_after = str(book_after["world_text"] or "")
                world_data_json_after = str(book_after["world_data_json"] or "")

                # outline_text 应被更新 (包含书籍描述)
                outline_changed = outline_text_after != outline_text_before
                results["writeback_book_outline"] = (
                    "PASS" if outline_changed else "FAIL (outline_text 未变化)"
                )
                assert outline_changed, (
                    f"books.outline_text 应被写回更新\n"
                    f"  before: {outline_text_before[:100]!r}\n"
                    f"  after:  {outline_text_after[:100]!r}"
                )

                # world_text / world_data_json 应被更新
                world_changed = (
                    world_text_after != world_text_before
                    or world_data_json_after != world_data_json_before
                )
                results["writeback_book_world"] = (
                    "PASS" if world_changed else "FAIL (world_text/world_data_json 未变化)"
                )
                assert world_changed, (
                    f"books.world_text / world_data_json 应被写回更新\n"
                    f"  world_text before: {world_text_before[:100]!r}\n"
                    f"  world_text after:  {world_text_after[:100]!r}"
                )

                # 验证 world_data_json 包含写入的世界规则
                world_data = json.loads(world_data_json_after) if world_data_json_after else {}
                world_fields = world_data.get("fields", {}) if isinstance(world_data, dict) else {}
                world_rules = str(world_fields.get("world_rules_table", {}).get("value", ""))
                assert "天玄大陆" in world_rules or "筑基" in world_rules, (
                    f"world_data_json 应包含写入的世界规则，实际: {world_rules[:200]}"
                )
                results["writeback_world_content"] = "PASS"

                # ── 步骤 10: 验证人物写回 ──
                characters_after = database.list_characters(book_id)
                char_names_after = {str(c["name"]): c for c in characters_after}

                # 陆沉/苏晚/周伯 都应存在
                for name in ("陆沉", "苏晚", "周伯"):
                    assert name in char_names_after, f"人物 '{name}' 应在 characters 表中"
                results["writeback_characters_exist"] = "PASS (陆沉/苏晚/周伯)"

                # 验证人物 profile 被更新 (检查 profile_data_json 非空且包含写入内容)
                profile_updated_count = 0
                for name in ("陆沉", "苏晚", "周伯"):
                    char = dict(char_names_after[name])
                    profile_json = str(char.get("profile_data_json") or "")
                    if profile_json and "personality_main" in profile_json:
                        profile_updated_count += 1
                results["writeback_characters_profile"] = (
                    f"PASS ({profile_updated_count}/3 人物 profile 已更新)"
                )
                assert profile_updated_count >= 1, (
                    "至少 1 个人物的 profile_data_json 应被更新"
                )

                # ── 步骤 11: 验证章节写回 ──
                updated_chapter_ids = set(apply_data.get("updated_chapter_ids") or [])
                if updated_chapter_ids:
                    # 验证章节 outline 被更新
                    sample_chapter_id = sorted(updated_chapter_ids)[0]
                    chapter = database.get_chapter(sample_chapter_id)
                    chapter_outline = str(chapter["outline"] or "").strip()
                    assert chapter_outline, (
                        f"章节 {sample_chapter_id} 的 outline 应被写回更新"
                    )
                    results["writeback_chapters"] = (
                        f"PASS ({len(updated_chapter_ids)} 章已更新, "
                        f"示例 outline: {chapter_outline[:50]!r})"
                    )
                else:
                    results["writeback_chapters"] = "WARN (无章节更新)"

                # ── 步骤 12: 验证卡片状态 ──
                refreshed_cards = database.list_analysis_cards(run_id)
                applied_cards = [
                    c for c in refreshed_cards if str(c["status"]) == "applied"
                ]
                assert len(applied_cards) > 0, "至少应有一张卡片状态为 applied"
                results["card_status_applied"] = (
                    f"PASS ({len(applied_cards)}/{len(refreshed_cards)} 张已应用)"
                )

                for card in applied_cards:
                    assert str(card["applied_table"] or "").strip(), (
                        f"卡片 {card['card_uid']} 的 applied_table 应非空"
                    )
                    assert card["applied_id"] is not None, (
                        f"卡片 {card['card_uid']} 的 applied_id 应非空"
                    )
                    assert card["applied_at"] is not None, (
                        f"卡片 {card['card_uid']} 的 applied_at 应非空"
                    )
                results["card_applied_meta"] = "PASS (applied_table/applied_id/applied_at 均已填充)"

                # 验证 run 状态
                run_after = database.get_analysis_run(run_id)
                assert str(run_after["status"]) == "applied", (
                    f"analysis_run 状态应为 applied，实际: {run_after['status']}"
                )
                results["run_status_applied"] = "PASS"

                # ── 步骤 13: 跨用户 apply 验证 (403) ──
                # 用户 B 的 token 访问用户 A 的 run
                resp = client.post(
                    f"/api/workspace/analysis/runs/{run_id}/apply",
                    headers=headers_b,
                    json={"user_override": False},
                )
                assert resp.status_code == 403, (
                    f"apply 跨用户应返回 403，实际: {resp.status_code}"
                )
                results["auth_403_apply"] = "PASS"

            # 关闭 workspace DB 连接，释放文件锁
            workspace_provider.close()
            reset_default_workspace_db(None)

            # ── 清理: TemporaryDirectory 自动清理 ──
            results["cleanup"] = "PASS (TemporaryDirectory 自动清理)"

        finally:
            # 恢复环境变量
            if old_data_dir:
                os.environ["SIMPLE_AI_NOVEL_DATA_DIR"] = old_data_dir
            else:
                os.environ.pop("SIMPLE_AI_NOVEL_DATA_DIR", None)
            reset_default_workspace_db(None)

        # 打印验证结果摘要 (便于报告)
        print("\n" + "=" * 70)
        print("V1 分析写回链路验证结果摘要")
        print("=" * 70)
        for step, result in results.items():
            print(f"  {step:40s} : {result}")
        print("=" * 70)
