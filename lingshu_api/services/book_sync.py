"""
书籍匹配与同步服务 — 本地 novels.db 与云端 bookstore 数据库之间的双向同步。

核心职责：
1. match_local_to_cloud  — 判断本地书籍与云端书籍是否为同一本书
2. upload_book_to_cloud  — 将本地书籍完整上传到云端
3. sync_uploaded_books   — 对已上传书籍按 updated_at 决定同步方向
4. download_cloud_book   — 将云端书籍下载到本地
"""
from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from lingshu_api.services.db_bridge import WorkspaceDB
from novel_app.bookstore import CloudBookStore

logger = logging.getLogger(__name__)

_VALID_LOCAL_TABLES = frozenset({
    "chapter_events", "chapter_tags", "review_findings", "review_runs",
    "analysis_cards", "analysis_runs", "character_relationships",
    "characters", "world_entries", "chapter_ai_spans", "chapter_snapshots",
    "chapters", "volumes",
})

def _validate_local_table(table_name: str) -> str:
    """校验本地动态表名是否在白名单中，防止 SQL 注入。"""
    if table_name not in _VALID_LOCAL_TABLES:
        raise ValueError(f"Invalid local table name: {table_name}")
    return table_name


def _content_similarity(text1: str, text2: str) -> float:
    """计算两个文本的字符级相似度（0.0-1.0）。"""
    if not text1 or not text2:
        return 0.0
    s1, s2 = text1[:500], text2[:500]
    if s1 == s2:
        return 1.0
    return SequenceMatcher(None, s1, s2).ratio()


def _parse_datetime(value: str | None) -> datetime | None:
    """将 SQLite datetime 字符串解析为 UTC datetime。"""
    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(str(value), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


class BookSyncService:
    """书籍匹配与同步服务。"""

    def __init__(
        self,
        cloud_store: CloudBookStore,
        workspace_db_factory: Callable[[], WorkspaceDB],
    ) -> None:
        self.cloud_store = cloud_store
        self.workspace_db_factory = workspace_db_factory

    # ================================================================
    #  1. match_local_to_cloud
    # ================================================================

    def match_local_to_cloud(
        self,
        local_book_id: int,
        user_id: int,
    ) -> int | None:
        """判断本地书籍与云端书籍是否为同一本书，返回匹配到的 cloud_book_id 或 None。

        匹配优先级：
        1. 按 cloud_book_id 绑定匹配（本地 books 表的 cloud_book_id 字段）
        2. 按标题精确匹配 + 首章内容前 500 字符相似度 > 80%
        """
        db = self.workspace_db_factory()
        try:
            local_book = db.get_book(local_book_id)
            if not local_book:
                logger.warning("match_local_to_cloud: 本地书籍 %d 不存在", local_book_id)
                return None

            # 优先级 1：按 cloud_book_id 绑定匹配
            cloud_book_id_str = local_book.get("cloud_book_id")
            if cloud_book_id_str:
                try:
                    cloud_book_id = int(cloud_book_id_str)
                except (ValueError, TypeError):
                    cloud_book_id = None
                if cloud_book_id:
                    cloud_book = self.cloud_store.get_cloud_book(user_id, cloud_book_id)
                    if cloud_book:
                        logger.info(
                            "match_local_to_cloud: 本地书籍 %d 通过 cloud_book_id=%d 绑定匹配",
                            local_book_id,
                            cloud_book_id,
                        )
                        return cloud_book_id

            # 优先级 2：按标题精确匹配
            local_title = local_book.get("title", "")
            cloud_books = self.cloud_store.list_cloud_books(user_id)
            candidates = [cb for cb in cloud_books if cb.get("title") == local_title]

            if not candidates:
                return None

            if len(candidates) == 1:
                cloud_book_id = int(candidates[0]["id"])
                # 进一步验证：首章内容相似度
                if self._verify_first_chapter_similarity(db, local_book_id, cloud_book_id):
                    logger.info(
                        "match_local_to_cloud: 本地书籍 %d 通过标题+内容匹配 cloud_book_id=%d",
                        local_book_id,
                        cloud_book_id,
                    )
                    return cloud_book_id
                logger.info(
                    "match_local_to_cloud: 本地书籍 %d 标题匹配但内容相似度不足，跳过",
                    local_book_id,
                )
                return None

            # 多个同名书籍，逐个验证内容
            for candidate in candidates:
                cloud_book_id = int(candidate["id"])
                if self._verify_first_chapter_similarity(db, local_book_id, cloud_book_id):
                    logger.info(
                        "match_local_to_cloud: 本地书籍 %d 通过标题+内容匹配 cloud_book_id=%d",
                        local_book_id,
                        cloud_book_id,
                    )
                    return cloud_book_id

            return None
        finally:
            db.close()

    def _verify_first_chapter_similarity(
        self,
        db: WorkspaceDB,
        local_book_id: int,
        cloud_book_id: int,
    ) -> bool:
        """取首章内容前 500 字符做相似度校验，> 80% 确认为同一本书。"""
        local_content = self._get_local_first_chapter_content(db, local_book_id)
        cloud_content = self._get_cloud_first_chapter_content(cloud_book_id)

        if not local_content and not cloud_content:
            # 两边都没有章节内容，视为匹配（例如空书）
            return True
        if not local_content or not cloud_content:
            return False

        similarity = _content_similarity(local_content, cloud_content)
        logger.debug(
            "首章内容相似度: local_book=%d cloud_book=%d similarity=%.2f",
            local_book_id,
            cloud_book_id,
            similarity,
        )
        return similarity > 0.8

    def _get_local_first_chapter_content(self, db: WorkspaceDB, book_id: int) -> str:
        """获取本地书籍首章内容。"""
        conn = db.db.connection
        row = conn.execute(
            "SELECT content FROM chapters WHERE book_id = ? ORDER BY sort_order ASC, id ASC LIMIT 1",
            (book_id,),
        ).fetchone()
        return str(row["content"]) if row and row["content"] else ""

    def _get_cloud_first_chapter_content(self, cloud_book_id: int) -> str:
        """获取云端书籍首章内容。"""
        with self.cloud_store.db_path and sqlite3.connect(self.cloud_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT content FROM cloud_chapters WHERE cloud_book_id = ? ORDER BY sort_order ASC, id ASC LIMIT 1",
                (cloud_book_id,),
            ).fetchone()
            return str(row["content"]) if row and row["content"] else ""

    # ================================================================
    #  2. upload_book_to_cloud
    # ================================================================

    def upload_book_to_cloud(
        self,
        local_book_id: int,
        user_id: int,
    ) -> int | None:
        """将指定书籍完整上传到云端（含全部关联数据），返回 cloud_book_id 或 None。"""
        db = self.workspace_db_factory()
        try:
            local_book = db.get_book(local_book_id)
            if not local_book:
                logger.error("upload_book_to_cloud: 本地书籍 %d 不存在", local_book_id)
                return None

            # 检查是否已上传
            existing_cloud_id = local_book.get("cloud_book_id")
            if existing_cloud_id:
                try:
                    existing_id = int(existing_cloud_id)
                    cloud_book = self.cloud_store.get_cloud_book(user_id, existing_id)
                    if cloud_book:
                        logger.info(
                            "upload_book_to_cloud: 本地书籍 %d 已上传为 cloud_book_id=%d，跳过",
                            local_book_id,
                            existing_id,
                        )
                        return existing_id
                except (ValueError, TypeError):
                    pass

            conn = db.db.connection

            # ── 开启云端事务 ──
            self.cloud_store.begin_transaction()
            try:
                # ── 书籍元数据 → cloud_books ──
                cloud_book_id = self.cloud_store.create_cloud_book(
                    user_id=user_id,
                    title=local_book.get("title", ""),
                    outline_text=local_book.get("outline_text", ""),
                    outline_data_json=local_book.get("outline_data_json", ""),
                    world_text=local_book.get("world_text", ""),
                    world_data_json=local_book.get("world_data_json", ""),
                    cover_image_path=local_book.get("cover_image_path", ""),
                    local_book_id=local_book_id,
                    source_type="user_upload",
                )
                logger.info("upload_book_to_cloud: 创建 cloud_book_id=%d", cloud_book_id)

                # ── 同步关联数据 ──
                self._sync_book_relations(local_book_id, cloud_book_id, conn)

                # ── 提交云端事务 ──
                self.cloud_store.commit_transaction()
            except Exception:
                self.cloud_store.rollback_transaction()
                logger.exception("upload_book_to_cloud: 云端事务回滚, local_book_id=%s", local_book_id)
                raise

            # ── 更新本地 books 表的 cloud_book_id 绑定 ──
            conn.execute(
                "UPDATE books SET cloud_book_id = ? WHERE id = ?",
                (str(cloud_book_id), local_book_id),
            )
            conn.commit()
            logger.info(
                "upload_book_to_cloud: 本地书籍 %d 上传完成，cloud_book_id=%d",
                local_book_id,
                cloud_book_id,
            )

            return cloud_book_id
        except Exception:
            logger.exception("upload_book_to_cloud: 本地书籍 %d 上传失败", local_book_id)
            return None
        finally:
            db.close()

    # ================================================================
    #  3. sync_uploaded_books
    # ================================================================

    def sync_uploaded_books(self, user_id: int) -> dict[str, int]:
        """登录后仅对已上传书籍同步，按 updated_at 决定方向。

        返回同步结果摘要：{"uploaded": N, "downloaded": N, "skipped": N, "conflicts": N}
        """
        result = {"uploaded": 0, "downloaded": 0, "skipped": 0, "conflicts": 0}

        db = self.workspace_db_factory()
        try:
            local_books = db.list_books()

            # 收集所有有 cloud_book_id 绑定的书籍及对应的 cloud_book_id
            bound_books: list[tuple[dict, int]] = []
            cloud_book_ids: list[int] = []
            for book in local_books:
                cb_id = book.get("cloud_book_id")
                if not cb_id:
                    continue
                try:
                    cb_id_int = int(cb_id)
                    bound_books.append((book, cb_id_int))
                    cloud_book_ids.append(cb_id_int)
                except (ValueError, TypeError):
                    logger.warning(
                        "sync_uploaded_books: 本地书籍 %d 的 cloud_book_id=%r 无效，跳过",
                        book.get("id"),
                        cb_id,
                    )
                    continue

            if not bound_books:
                logger.info("sync_uploaded_books: 没有已绑定云端的书籍")
                return result

            # 批量获取云端数据（替代 N 次 get_cloud_book）
            cloud_books_map: dict[int, dict] = {}
            if cloud_book_ids:
                cloud_books = self.cloud_store.list_cloud_books_by_ids(user_id, cloud_book_ids)
                cloud_books_map = {cb["id"]: cb for cb in cloud_books}

            for local_book, cloud_book_id in bound_books:
                local_book_id = int(local_book["id"])

                try:
                    cloud_book = cloud_books_map.get(cloud_book_id)
                    if not cloud_book:
                        logger.warning(
                            "sync_uploaded_books: cloud_book_id=%d 不存在，跳过",
                            cloud_book_id,
                        )
                        result["skipped"] += 1
                        continue

                    local_updated = _parse_datetime(local_book.get("updated_at"))
                    cloud_updated = _parse_datetime(cloud_book.get("updated_at"))

                    if local_updated is None and cloud_updated is None:
                        result["skipped"] += 1
                        continue

                    if local_updated is None:
                        # 云端有更新时间，本地没有 → 下载
                        self._download_cloud_book_data(user_id, cloud_book_id, local_book_id)
                        result["downloaded"] += 1
                        continue

                    if cloud_updated is None:
                        # 本地有更新时间，云端没有 → 上传
                        self._upload_book_overwrite(user_id, cloud_book_id, local_book_id)
                        result["uploaded"] += 1
                        continue

                    diff = abs((local_updated - cloud_updated).total_seconds())
                    if diff <= 1.0:
                        # 时间差 ≤1s → 保留本地版本
                        result["skipped"] += 1
                        continue

                    if local_updated > cloud_updated:
                        # 本地更新 → 上传覆盖云端
                        self._upload_book_overwrite(user_id, cloud_book_id, local_book_id)
                        result["uploaded"] += 1
                    else:
                        # 云端更新 → 下载覆盖本地
                        self._download_cloud_book_data(user_id, cloud_book_id, local_book_id)
                        result["downloaded"] += 1

                except Exception:
                    logger.exception(
                        "sync_uploaded_books: 同步本地书籍 %d (cloud_book_id=%d) 失败",
                        local_book_id,
                        cloud_book_id,
                    )
                    result["conflicts"] += 1

            return result
        finally:
            db.close()

    def _upload_book_overwrite(
        self,
        user_id: int,
        cloud_book_id: int,
        local_book_id: int,
    ) -> None:
        """上传覆盖云端书籍数据（先删除云端旧数据，再重新上传）。"""
        # 删除云端书籍及其关联数据（CASCADE 会级联删除）
        self.cloud_store.delete_cloud_book(user_id, cloud_book_id)

        # 重新上传（此时本地 books.cloud_book_id 会被清除，需要重新绑定）
        new_cloud_id = self.upload_book_to_cloud(local_book_id, user_id)
        if new_cloud_id is None:
            logger.error(
                "_upload_book_overwrite: 重新上传本地书籍 %d 失败",
                local_book_id,
            )

    # ================================================================
    #  4. download_cloud_book
    # ================================================================

    def download_cloud_book(
        self,
        cloud_book_id: int,
        user_id: int,
    ) -> int | None:
        """将云端书籍及全部关联数据下载到本地，返回本地 book_id 或 None。"""
        cloud_book = self.cloud_store.get_cloud_book(user_id, cloud_book_id)
        if not cloud_book:
            logger.error("download_cloud_book: cloud_book_id=%d 不存在", cloud_book_id)
            return None

        db = self.workspace_db_factory()
        try:
            local_book_id = self._download_cloud_book_data(user_id, cloud_book_id)
            return local_book_id
        except Exception:
            logger.exception("download_cloud_book: 下载 cloud_book_id=%d 失败", cloud_book_id)
            return None
        finally:
            db.close()

    def _download_cloud_book_data(
        self,
        user_id: int,
        cloud_book_id: int,
        existing_local_book_id: int | None = None,
    ) -> int | None:
        """从云端读取数据写入本地 novels.db，建立 cloud_book_id 绑定。

        如果 existing_local_book_id 不为 None，则覆盖该本地书籍；
        否则创建新的本地书籍。
        """
        cloud_book = self.cloud_store.get_cloud_book(user_id, cloud_book_id)
        if not cloud_book:
            return None

        db = self.workspace_db_factory()
        try:
            conn = db.db.connection

            # ── 开启本地事务 ──
            conn.execute("BEGIN IMMEDIATE")
            try:
                # ── 书籍元数据 ──
                if existing_local_book_id:
                    local_book_id = existing_local_book_id
                    conn.execute(
                        "UPDATE books SET title = ?, outline_text = ?, outline_data_json = ?, "
                        "world_text = ?, world_data_json = ?, cover_image_path = ?, "
                        "cloud_book_id = ?, user_id = ? WHERE id = ?",
                        (
                            cloud_book["title"] or "",
                            cloud_book["outline_text"] or "",
                            cloud_book["outline_data_json"] or "",
                            cloud_book["world_text"] or "",
                            cloud_book["world_data_json"] or "",
                            cloud_book["cover_image_path"] or "",
                            str(cloud_book_id),
                            user_id,
                            local_book_id,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        "INSERT INTO books (title, outline_text, outline_data_json, "
                        "world_text, world_data_json, cover_image_path, cloud_book_id, user_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            cloud_book["title"] or "",
                            cloud_book["outline_text"] or "",
                            cloud_book["outline_data_json"] or "",
                            cloud_book["world_text"] or "",
                            cloud_book["world_data_json"] or "",
                            cloud_book["cover_image_path"] or "",
                            str(cloud_book_id),
                            user_id,
                        ),
                    )
                    local_book_id = int(cursor.lastrowid)

                # ID 映射：cloud_id → local_id
                volume_id_map: dict[int, int] = {}
                chapter_id_map: dict[int, int] = {}
                character_id_map: dict[int, int] = {}
                analysis_run_id_map: dict[int, int] = {}
                review_run_id_map: dict[int, int] = {}

                # 如果覆盖已有书籍，先清除关联数据
                if existing_local_book_id:
                    for table in (
                        "chapter_events",
                        "chapter_tags",
                        "review_findings",
                        "review_runs",
                        "analysis_cards",
                        "analysis_runs",
                        "character_relationships",
                        "characters",
                        "world_entries",
                        "chapter_ai_spans",
                        "chapter_snapshots",
                        "chapters",
                        "volumes",
                    ):
                        with contextlib.suppress(sqlite3.OperationalError):
                            conn.execute(f"DELETE FROM {_validate_local_table(table)} WHERE book_id = ?", (local_book_id,))
                    # review_findings 通过 run_id 关联
                    conn.execute(
                        "DELETE FROM review_findings WHERE run_id IN "
                        "(SELECT id FROM review_runs WHERE book_id = ?)",
                        (local_book_id,),
                    )

                # ── 分卷 ──
                cloud_volumes = self._query_cloud(
                    "SELECT * FROM cloud_volumes WHERE cloud_book_id = ? ORDER BY sort_order ASC, id ASC",
                    (cloud_book_id,),
                )
                for cv in cloud_volumes:
                    cursor = conn.execute(
                        "INSERT INTO volumes (book_id, title, outline_text, sort_order) VALUES (?, ?, ?, ?)",
                        (local_book_id, cv["title"] or "", cv["outline_text"] or "", int(cv["sort_order"] or 0)),
                    )
                    vid = int(cursor.lastrowid)
                    volume_id_map[int(cv["id"])] = vid

                # ── 章节 ──
                cloud_chapters = self._query_cloud(
                    "SELECT * FROM cloud_chapters WHERE cloud_book_id = ? ORDER BY sort_order ASC, id ASC",
                    (cloud_book_id,),
                )
                for cch in cloud_chapters:
                    cloud_vol_id = cch["cloud_volume_id"]
                    local_vol_id = volume_id_map.get(int(cloud_vol_id)) if cloud_vol_id else None
                    cursor = conn.execute(
                        "INSERT INTO chapters (book_id, volume_id, title, outline, content, summary_text, "
                        "chapter_type, sort_order, ai_probability, ai_probability_level) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            local_vol_id,
                            cch["title"] or "",
                            cch["outline"] or "",
                            cch["content"] or "",
                            cch["summary_text"] or "",
                            cch.get("chapter_type", "正文"),
                            int(cch["sort_order"] or 0),
                            int(cch["ai_probability"] or 0),
                            cch["ai_probability_level"] or "none",
                        ),
                    )
                    cid = int(cursor.lastrowid)
                    chapter_id_map[int(cch["id"])] = cid

                # ── 人物卡 ──
                cloud_characters = self._query_cloud(
                    "SELECT * FROM cloud_characters WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for cchar in cloud_characters:
                    cursor = conn.execute(
                        "INSERT INTO characters (book_id, name, role, profile_text, profile_data_json, "
                        "image_path, graph_x, graph_y) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            cchar["name"] or "",
                            cchar["role"] or "",
                            cchar["profile_text"] or "",
                            cchar["profile_data_json"] or "",
                            cchar["image_path"] or "",
                            float(cchar["graph_x"] or 0),
                            float(cchar["graph_y"] or 0),
                        ),
                    )
                    char_id = int(cursor.lastrowid)
                    character_id_map[int(cchar["id"])] = char_id

                # ── 人物关系 ──
                cloud_relationships = self._query_cloud(
                    "SELECT * FROM cloud_character_relationships WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for crel in cloud_relationships:
                    source_local = character_id_map.get(int(crel["source_character_id"]))
                    target_local = character_id_map.get(int(crel["target_character_id"]))
                    if source_local is not None and target_local is not None:
                        conn.execute(
                            "INSERT INTO character_relationships "
                            "(book_id, source_character_id, target_character_id, relationship_type, description) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (
                                local_book_id,
                                source_local,
                                target_local,
                                crel["relationship_type"] or "",
                                crel["description"] or "",
                            ),
                        )

                # ── 世界观 ──
                cloud_world_entries = self._query_cloud(
                    "SELECT * FROM cloud_world_entries WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for cwe in cloud_world_entries:
                    conn.execute(
                        "INSERT INTO world_entries (book_id, name, category, content_text) VALUES (?, ?, ?, ?)",
                        (
                            local_book_id,
                            cwe["name"] or "",
                            cwe["category"] or "设定",
                            cwe["content_text"] or "",
                        ),
                    )

                # ── 分析运行 ──
                cloud_analysis_runs = self._query_cloud(
                    "SELECT * FROM cloud_analysis_runs WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for car in cloud_analysis_runs:
                    cursor = conn.execute(
                        "INSERT INTO analysis_runs "
                        "(book_id, scope_type, status, pipeline_version, input_hash, summary, error_text, meta_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            car["scope_type"] or "book",
                            car["status"] or "created",
                            car["pipeline_version"] or "draft_mvp_v1",
                            car["input_hash"] or "",
                            car["summary"] or "",
                            car["error_text"] or "",
                            car["meta_json"] or "{}",
                        ),
                    )
                    analysis_run_id_map[int(car["id"])] = int(cursor.lastrowid)

                # ── 分析卡 ──
                cloud_analysis_cards = self._query_cloud(
                    "SELECT * FROM cloud_analysis_cards WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for cac in cloud_analysis_cards:
                    local_run_id = analysis_run_id_map.get(int(cac["cloud_run_id"]))
                    if local_run_id is None:
                        continue
                    conn.execute(
                        "INSERT INTO analysis_cards "
                        "(book_id, run_id, card_uid, card_type, entity_uid, card_version, "
                        "ars_score, status, payload_json, diff_json, applied_table, applied_id, applied_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            local_run_id,
                            cac["card_uid"] or "",
                            cac["card_type"] or "",
                            cac["entity_uid"] or "",
                            int(cac["card_version"] or 1),
                            float(cac["ars_score"] or 0),
                            cac["status"] or "draft",
                            cac["payload_json"] or "{}",
                            cac["diff_json"] or "{}",
                            cac["applied_table"] or "",
                            cac["applied_id"] if cac["applied_id"] is not None else None,
                            cac["applied_at"] if cac["applied_at"] is not None else None,
                        ),
                    )

                # ── 审查运行 ──
                cloud_review_runs = self._query_cloud(
                    "SELECT * FROM cloud_review_runs WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for crr in cloud_review_runs:
                    local_chapter_id = chapter_id_map.get(int(crr["cloud_chapter_id"])) if crr["cloud_chapter_id"] else None
                    cursor = conn.execute(
                        "INSERT INTO review_runs "
                        "(book_id, chapter_id, scope_type, status, truth_snapshot, summary, overall_score) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            local_chapter_id,
                            crr["scope_type"] or "chapter",
                            crr["status"] or "completed",
                            crr["truth_snapshot"] or "",
                            crr["summary"] or "",
                            int(crr["overall_score"] or 0),
                        ),
                    )
                    review_run_id_map[int(crr["id"])] = int(cursor.lastrowid)

                # ── 审查发现 ──
                cloud_review_findings = self._query_cloud(
                    "SELECT * FROM cloud_review_findings WHERE cloud_run_id IN "
                    "(SELECT id FROM cloud_review_runs WHERE cloud_book_id = ?)",
                    (cloud_book_id,),
                )
                for crf in cloud_review_findings:
                    local_run_id = review_run_id_map.get(int(crf["cloud_run_id"]))
                    if local_run_id is None:
                        continue
                    conn.execute(
                        "INSERT INTO review_findings "
                        "(run_id, agent, severity, category, location_hint, quote_text, issue_text, suggestion_text) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            local_run_id,
                            crf["agent"] or "",
                            crf["severity"] or "low",
                            crf["category"] or "",
                            crf["location_hint"] or "",
                            crf["quote_text"] or "",
                            crf["issue_text"] or "",
                            crf["suggestion_text"] or "",
                        ),
                    )

                # ── 章节事件 ──
                cloud_chapter_events = self._query_cloud(
                    "SELECT * FROM cloud_chapter_events WHERE cloud_book_id = ?",
                    (cloud_book_id,),
                )
                for cce in cloud_chapter_events:
                    local_ch_id = chapter_id_map.get(int(cce["cloud_chapter_id"]))
                    if local_ch_id is None:
                        continue
                    conn.execute(
                        "INSERT INTO chapter_events (book_id, chapter_id, label, description, sort_order) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            local_book_id,
                            local_ch_id,
                            cce["label"] or "",
                            cce["description"] or "",
                            int(cce["sort_order"] or 0),
                        ),
                    )

                # ── 章节标签 ──
                cloud_chapter_tags = self._query_cloud(
                    "SELECT * FROM cloud_chapter_tags WHERE cloud_chapter_id IN "
                    "(SELECT id FROM cloud_chapters WHERE cloud_book_id = ?)",
                    (cloud_book_id,),
                )
                for cct in cloud_chapter_tags:
                    local_ch_id = chapter_id_map.get(int(cct["cloud_chapter_id"]))
                    if local_ch_id is None:
                        continue
                    with contextlib.suppress(sqlite3.IntegrityError):
                        conn.execute(
                            "INSERT INTO chapter_tags (chapter_id, tag) VALUES (?, ?)",
                            (local_ch_id, cct["tag"] or ""),
                        )

                # ── 提交本地事务 ──
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                logger.exception(
                    "_download_cloud_book_data: 本地事务回滚, cloud_book_id=%s", cloud_book_id,
                )
                raise

            logger.info(
                "_download_cloud_book_data: cloud_book_id=%d → local_book_id=%d 下载完成",
                cloud_book_id,
                local_book_id,
            )
            return local_book_id
        except Exception:
            logger.exception(
                "_download_cloud_book_data: 下载 cloud_book_id=%d 失败",
                cloud_book_id,
            )
            return None
        finally:
            db.close()

    def _query_cloud(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        """直接查询云端数据库，返回字典列表。"""
        with sqlite3.connect(self.cloud_store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def _sync_book_relations(
        self,
        local_book_id: int,
        cloud_book_id: int,
        conn,
    ) -> dict[str, dict[int, int]]:
        """同步书籍关联数据（分卷/章节/人物/世界观/分析/审查）。

        将本地书籍的全部关联数据同步到云端。调用方负责：
        - 开启/提交/回滚云端事务
        - 创建或更新云端书籍元数据
        - 如需更新，先删除旧关联数据

        Args:
            local_book_id: 本地书籍 ID
            cloud_book_id: 云端书籍 ID
            conn: 本地数据库连接

        Returns:
            id_maps: 各种 ID 映射关系，键为映射名称，值为 {local_id: cloud_id} 字典
        """
        volume_id_map: dict[int, int] = {}
        chapter_id_map: dict[int, int] = {}
        character_id_map: dict[int, int] = {}
        analysis_run_id_map: dict[int, int] = {}
        review_run_id_map: dict[int, int] = {}

        # ── 分卷 → cloud_volumes ──
        volumes = conn.execute(
            "SELECT * FROM volumes WHERE book_id = ? ORDER BY sort_order ASC, id ASC",
            (local_book_id,),
        ).fetchall()
        for vol in volumes:
            cloud_vol_id = self.cloud_store.create_cloud_volume(
                cloud_book_id=cloud_book_id,
                title=vol["title"] or "",
                outline_text=vol["outline_text"] or "",
                sort_order=int(vol["sort_order"] or 0),
                local_volume_id=int(vol["id"]),
            )
            volume_id_map[int(vol["id"])] = cloud_vol_id

        # ── 章节 → cloud_chapters ──
        chapters = conn.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY sort_order ASC, id ASC",
            (local_book_id,),
        ).fetchall()
        for ch in chapters:
            local_volume_id = ch["volume_id"]
            cloud_volume_id = volume_id_map.get(int(local_volume_id)) if local_volume_id else None
            cloud_ch_id = self.cloud_store.create_cloud_chapter(
                cloud_book_id=cloud_book_id,
                title=ch["title"] or "",
                outline=ch["outline"] or "",
                content=ch["content"] or "",
                summary_text=ch["summary_text"] or "",
                chapter_type=dict(ch).get("chapter_type") or "正文",
                sort_order=int(ch["sort_order"] or 0),
                ai_probability=int(ch["ai_probability"] or 0),
                ai_probability_level=ch["ai_probability_level"] or "none",
                cloud_volume_id=cloud_volume_id,
                local_chapter_id=int(ch["id"]),
            )
            chapter_id_map[int(ch["id"])] = cloud_ch_id

        # ── 人物卡 → cloud_characters ──
        characters = conn.execute(
            "SELECT * FROM characters WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for char in characters:
            cloud_char_id = self.cloud_store.create_cloud_character(
                cloud_book_id=cloud_book_id,
                name=char["name"] or "",
                role=char["role"] or "",
                profile_text=char["profile_text"] or "",
                profile_data_json=char["profile_data_json"] or "",
                image_path=char["image_path"] or "",
                graph_x=float(char["graph_x"] or 0),
                graph_y=float(char["graph_y"] or 0),
                local_character_id=int(char["id"]),
            )
            character_id_map[int(char["id"])] = cloud_char_id

        # ── 人物关系 → cloud_character_relationships ──
        relationships = conn.execute(
            "SELECT * FROM character_relationships WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for rel in relationships:
            source_cloud = character_id_map.get(int(rel["source_character_id"]))
            target_cloud = character_id_map.get(int(rel["target_character_id"]))
            if source_cloud is not None and target_cloud is not None:
                self.cloud_store.create_cloud_relationship(
                    cloud_book_id=cloud_book_id,
                    source_character_id=source_cloud,
                    target_character_id=target_cloud,
                    relationship_type=rel["relationship_type"] or "",
                    description=rel["description"] or "",
                )

        # ── 世界观 → cloud_world_entries ──
        world_entries = conn.execute(
            "SELECT * FROM world_entries WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for we in world_entries:
            self.cloud_store.create_cloud_world_entry(
                cloud_book_id=cloud_book_id,
                name=we["name"] or "",
                category=we["category"] or "设定",
                content_text=we["content_text"] or "",
                local_world_entry_id=int(we["id"]),
            )

        # ── 分析运行 → cloud_analysis_runs ──
        analysis_runs = conn.execute(
            "SELECT * FROM analysis_runs WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for ar in analysis_runs:
            cloud_run_id = self.cloud_store.create_cloud_analysis_run(
                cloud_book_id=cloud_book_id,
                scope_type=ar["scope_type"] or "book",
                status=ar["status"] or "created",
                pipeline_version=ar["pipeline_version"] or "draft_mvp_v1",
                input_hash=ar["input_hash"] or "",
                summary=ar["summary"] or "",
                error_text=ar["error_text"] or "",
                meta_json=ar["meta_json"] or "{}",
                local_run_id=int(ar["id"]),
            )
            analysis_run_id_map[int(ar["id"])] = cloud_run_id

        # ── 分析卡 → cloud_analysis_cards ──
        analysis_cards = conn.execute(
            "SELECT * FROM analysis_cards WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for ac in analysis_cards:
            cloud_run_id = analysis_run_id_map.get(int(ac["run_id"]))
            if cloud_run_id is None:
                continue
            self.cloud_store.create_cloud_analysis_card(
                cloud_book_id=cloud_book_id,
                cloud_run_id=cloud_run_id,
                card_uid=ac["card_uid"] or "",
                card_type=ac["card_type"] or "",
                payload_json=ac["payload_json"] or "{}",
                entity_uid=ac["entity_uid"] or "",
                card_version=int(ac["card_version"] or 1),
                ars_score=float(ac["ars_score"] or 0),
                status=ac["status"] or "draft",
                diff_json=ac["diff_json"] or "{}",
                applied_table=ac["applied_table"] or "",
                applied_id=ac["applied_id"] if ac["applied_id"] is not None else None,
                applied_at=ac["applied_at"] if ac["applied_at"] is not None else None,
                local_card_id=int(ac["id"]),
            )

        # ── 审查运行 → cloud_review_runs ──
        review_runs = conn.execute(
            "SELECT * FROM review_runs WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for rr in review_runs:
            cloud_chapter_id = chapter_id_map.get(int(rr["chapter_id"])) if rr["chapter_id"] else None
            cloud_review_run_id = self.cloud_store.create_cloud_review_run(
                cloud_book_id=cloud_book_id,
                cloud_chapter_id=cloud_chapter_id,
                scope_type=rr["scope_type"] or "chapter",
                status=rr["status"] or "completed",
                truth_snapshot=rr["truth_snapshot"] or "",
                summary=rr["summary"] or "",
                overall_score=int(rr["overall_score"] or 0),
                local_run_id=int(rr["id"]),
            )
            review_run_id_map[int(rr["id"])] = cloud_review_run_id

        # ── 审查发现 → cloud_review_findings ──
        review_findings = conn.execute(
            "SELECT * FROM review_findings WHERE run_id IN (SELECT id FROM review_runs WHERE book_id = ?)",
            (local_book_id,),
        ).fetchall()
        for rf in review_findings:
            cloud_run_id = review_run_id_map.get(int(rf["run_id"]))
            if cloud_run_id is None:
                continue
            self.cloud_store.create_cloud_review_finding(
                cloud_run_id=cloud_run_id,
                agent=rf["agent"] or "",
                severity=rf["severity"] or "low",
                category=rf["category"] or "",
                location_hint=rf["location_hint"] or "",
                quote_text=rf["quote_text"] or "",
                issue_text=rf["issue_text"] or "",
                suggestion_text=rf["suggestion_text"] or "",
            )

        # ── 章节事件 → cloud_chapter_events ──
        chapter_events = conn.execute(
            "SELECT * FROM chapter_events WHERE book_id = ?",
            (local_book_id,),
        ).fetchall()
        for ce in chapter_events:
            cloud_ch_id = chapter_id_map.get(int(ce["chapter_id"]))
            if cloud_ch_id is None:
                continue
            self.cloud_store.create_cloud_chapter_event(
                cloud_book_id=cloud_book_id,
                cloud_chapter_id=cloud_ch_id,
                label=ce["label"] or "",
                description=ce["description"] or "",
                sort_order=int(ce["sort_order"] or 0),
            )

        # ── 章节标签 → cloud_chapter_tags ──
        chapter_tags = conn.execute(
            "SELECT ct.* FROM chapter_tags ct "
            "INNER JOIN chapters c ON ct.chapter_id = c.id "
            "WHERE c.book_id = ?",
            (local_book_id,),
        ).fetchall()
        for ct in chapter_tags:
            cloud_ch_id = chapter_id_map.get(int(ct["chapter_id"]))
            if cloud_ch_id is None:
                continue
            self.cloud_store.add_cloud_chapter_tag(
                cloud_chapter_id=cloud_ch_id,
                tag=ct["tag"] or "",
            )

        return {
            "volume_id_map": volume_id_map,
            "chapter_id_map": chapter_id_map,
            "character_id_map": character_id_map,
            "analysis_run_id_map": analysis_run_id_map,
            "review_run_id_map": review_run_id_map,
        }

    # ================================================================
    #  5. silent_collect — 后台静默收集完整数据
    # ================================================================

    def silent_collect(self, local_book_id: int, user_id: int) -> None:
        """后台静默收集本地书籍完整数据到云端。

        与 upload_book_to_cloud 不同，此方法：
        1. 不更新本地 books.cloud_book_id 绑定
        2. 如果云端已存在该用户的同名书籍，则更新而非重复创建
        3. 失败时静默忽略，不抛异常
        """
        try:
            # 检查云端是否已有该用户的同名书籍
            cloud_book_id = self.match_local_to_cloud(local_book_id, user_id)
            if cloud_book_id:
                # 已存在，更新云端数据
                self._update_cloud_book_data(local_book_id, cloud_book_id, user_id)
            else:
                # 不存在，创建云端书籍（但不绑定 cloud_book_id）
                self._create_cloud_book_silent(local_book_id, user_id)
        except Exception:
            logger.exception("silent_collect: 书籍 %d 静默收集失败", local_book_id)

    # ================================================================
    #  6. sync_book_edit — 已上传书籍的编辑同步
    # ================================================================

    def sync_book_edit(self, local_book_id: int, user_id: int) -> None:
        """已上传书籍编辑后同步更新云端。

        仅对有 cloud_book_id 绑定的书籍生效。
        失败时静默忽略，不抛异常。
        """
        try:
            db = self.workspace_db_factory()
            try:
                local_book = db.get_book(local_book_id)
                if not local_book:
                    return
                cloud_book_id_str = local_book.get("cloud_book_id")
                if not cloud_book_id_str:
                    return  # 未上传云端，跳过
                cloud_book_id = int(cloud_book_id_str)
                self._update_cloud_book_data(local_book_id, cloud_book_id, user_id)
            finally:
                db.close()
        except Exception:
            logger.exception("sync_book_edit: 书籍 %d 同步更新失败", local_book_id)

    # ================================================================
    #  内部方法：_update_cloud_book_data / _create_cloud_book_silent
    # ================================================================

    def _update_cloud_book_data(
        self,
        local_book_id: int,
        cloud_book_id: int,
        user_id: int,
    ) -> None:
        """更新云端书籍数据：更新元数据，删除旧关联数据，重新创建关联数据。"""
        db = self.workspace_db_factory()
        try:
            local_book = db.get_book(local_book_id)
            if not local_book:
                return

            conn = db.db.connection

            # ── 开启云端事务 ──
            self.cloud_store.begin_transaction()
            try:
                # ── 更新云端书籍元数据 ──
                self.cloud_store.update_cloud_book(
                    user_id=user_id,
                    cloud_book_id=cloud_book_id,
                    title=local_book.get("title", ""),
                    outline_text=local_book.get("outline_text", ""),
                    outline_data_json=local_book.get("outline_data_json", ""),
                    world_text=local_book.get("world_text", ""),
                    world_data_json=local_book.get("world_data_json", ""),
                    cover_image_path=local_book.get("cover_image_path", ""),
                )

                # ── 删除云端旧关联数据（保留 cloud_books 记录） ──
                self.cloud_store.delete_cloud_book_relations(cloud_book_id)

                # ── 重新创建关联数据 ──
                self._sync_book_relations(local_book_id, cloud_book_id, conn)

                # ── 提交云端事务 ──
                self.cloud_store.commit_transaction()
            except Exception:
                self.cloud_store.rollback_transaction()
                logger.exception(
                    "_update_cloud_book_data: 云端事务回滚, cloud_book_id=%s", cloud_book_id,
                )
                raise

            logger.info(
                "_update_cloud_book_data: 本地书籍 %d → cloud_book_id=%d 更新完成",
                local_book_id,
                cloud_book_id,
            )
        except Exception:
            logger.exception(
                "_update_cloud_book_data: 更新本地书籍 %d → cloud_book_id=%d 失败",
                local_book_id,
                cloud_book_id,
            )
        finally:
            db.close()

    def _create_cloud_book_silent(
        self,
        local_book_id: int,
        user_id: int,
    ) -> None:
        """静默创建云端书籍（不绑定 cloud_book_id）。

        与 upload_book_to_cloud 类似，但不更新本地 books.cloud_book_id。
        """
        db = self.workspace_db_factory()
        try:
            local_book = db.get_book(local_book_id)
            if not local_book:
                return

            conn = db.db.connection

            # ── 开启云端事务 ──
            self.cloud_store.begin_transaction()
            try:
                # ── 书籍元数据 → cloud_books ──
                cloud_book_id = self.cloud_store.create_cloud_book(
                    user_id=user_id,
                    title=local_book.get("title", ""),
                    outline_text=local_book.get("outline_text", ""),
                    outline_data_json=local_book.get("outline_data_json", ""),
                    world_text=local_book.get("world_text", ""),
                    world_data_json=local_book.get("world_data_json", ""),
                    cover_image_path=local_book.get("cover_image_path", ""),
                    local_book_id=local_book_id,
                    source_type="silent_collect",
                )
                logger.info(
                    "_create_cloud_book_silent: 创建 cloud_book_id=%d（不绑定本地）",
                    cloud_book_id,
                )

                # ── 同步关联数据 ──
                self._sync_book_relations(local_book_id, cloud_book_id, conn)

                # ── 提交云端事务 ──
                self.cloud_store.commit_transaction()
            except Exception:
                self.cloud_store.rollback_transaction()
                logger.exception(
                    "_create_cloud_book_silent: 云端事务回滚, local_book_id=%s", local_book_id,
                )
                raise

            # 注意：不更新本地 books.cloud_book_id 绑定
            logger.info(
                "_create_cloud_book_silent: 本地书籍 %d 静默创建完成，cloud_book_id=%d",
                local_book_id,
                cloud_book_id,
            )
        except Exception:
            logger.exception(
                "_create_cloud_book_silent: 本地书籍 %d 静默创建失败",
                local_book_id,
            )
        finally:
            db.close()
