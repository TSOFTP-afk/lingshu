"""
V1 一次性分析 + 卡片写回完整测试。

测试流程:
1. 注册测试用户（复用 test_v3_ai 的 AI 配置）
2. 获取范例书籍
3. 调用 V1 一次性分析 POST /books/{book_id}/analysis-v1/one-shot
4. 查看分析卡片 GET /analysis/runs/{run_id}/cards
5. 调用写回 POST /analysis/runs/{run_id}/apply
6. 验证写回结果（人物/世界观/大纲是否更新）
"""
import asyncio
import time
import aiohttp

BASE = "https://www.ling-shu.top"


async def main():
    timeout = aiohttp.ClientTimeout(total=3600)  # V1 分析可能需要很久
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. 注册测试用户
        stamp = int(time.time())
        username = f"v1_test_{stamp}"
        password = "V1Test1234"
        print(f"\n=== 注册测试用户: {username} ===")
        async with session.post(f"{BASE}/api/auth/register",
                                json={"username": username, "password": password, "is_author": False}) as r:
            data = await r.json()
            token = data.get("access_token", "")
            user_id = data.get("user", {}).get("id", 0)
            print(f"  user_id={user_id} token={'OK' if token else 'MISSING'}")
            if not token or not user_id:
                print("注册失败，退出")
                return

        headers = {"Authorization": f"Bearer {token}"}

        # 2. 设置 AI 配置
        print(f"\n=== 设置 AI 配置 ===")
        ai_config = {
            "remote_enabled": True,
            "provider": "deepseek",
            "api_key": "sk-81f28dea2df94eaaa676e3e3bb709af4",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "temperature": 0.7,
            "max_tokens": 4096,
            "thinking_enabled": False,
            "thinking_budget_tokens": 10000,
            "interval_seconds": 8,
            "auto_write_threshold": 0.55,
            "probe_enabled": False,
        }
        profiles = {p: ai_config for p in ["book_analysis", "writing", "outline", "detector",
                                            "correction", "import", "skills", "review", "chat", "writing_probe"]}
        async with session.put(f"{BASE}/api/settings/ai", json={"profiles": profiles}, headers=headers) as r:
            print(f"  PUT /api/settings/ai: {r.status}")

        # 3. 获取范例书籍
        print(f"\n=== 获取范例书籍 ===")
        async with session.get(f"{BASE}/api/workspace/books", headers=headers) as r:
            data = await r.json()
            items = data.get("items", [])
            if not items:
                print("  无书籍，退出")
                return
            book_id = int(items[0]["id"])
            print(f"  book_id={book_id} title={items[0].get('title', '')[:30]}")

        # 4. 记录写回前状态
        print(f"\n=== 写回前状态 ===")
        before = await snapshot(session, headers, book_id)

        # 5. V1 一次性分析
        print(f"\n=== V1 一次性分析 (可能需要 5-15 分钟) ===")
        start = time.time()
        run_id = 0
        try:
            async with session.post(f"{BASE}/api/workspace/books/{book_id}/analysis-v1/one-shot",
                                    json={}, headers=headers, timeout=aiohttp.ClientTimeout(total=3000)) as r:
                status = r.status
                body = await r.json()
                elapsed = int(time.time() - start)
                print(f"  [{elapsed}s] HTTP {status}")
                if status != 200:
                    print(f"  错误: {body}")
                    return
                run_id = int(body.get("run_id", 0) or body.get("item", {}).get("id", 0))
                print(f"  run_id={run_id}")
                print(f"  card_count={body.get('card_count', body.get('item', {}).get('card_count', '?'))}")
                print(f"  draft_count={body.get('draft_count', body.get('item', {}).get('draft_count', '?'))}")
        except Exception as e:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] 分析失败: {e}")
            return

        if not run_id:
            print("  未获得 run_id，退出")
            return

        # 6. 查看卡片列表
        print(f"\n=== 分析卡片列表 ===")
        async with session.get(f"{BASE}/api/workspace/analysis/runs/{run_id}/cards", headers=headers) as r:
            data = await r.json()
            cards = data.get("items", [])
            print(f"  共 {len(cards)} 张卡片:")
            for c in cards:
                ctype = c.get("card_type", "")
                status_str = c.get("status", "")
                score = c.get("ars_score", 0)
                uid = c.get("card_uid", "")[:20]
                print(f"    [{ctype}] {uid} score={score} status={status_str}")

        if not cards:
            print("  无卡片，退出")
            return

        # 7. 调用写回
        print(f"\n=== 写回 (POST /analysis/runs/{run_id}/apply) ===")
        start = time.time()
        try:
            async with session.post(f"{BASE}/api/workspace/analysis/runs/{run_id}/apply",
                                    json={}, headers=headers, timeout=aiohttp.ClientTimeout(total=600)) as r:
                status = r.status
                body = await r.json()
                elapsed = int(time.time() - start)
                print(f"  [{elapsed}s] HTTP {status}")
                if status == 200:
                    print(f"  ok={body.get('ok')}")
                    print(f"  applied_cards={body.get('applied_cards')}")
                    print(f"  skipped_cards={body.get('skipped_cards')}")
                    print(f"  updated_chapter_ids={body.get('updated_chapter_ids', [])[:5]}...")
                    print(f"  unresolved_count={body.get('unresolved_count')}")
                    print(f"  evidence_gate_dropped={body.get('evidence_gate_dropped')}")
                    print(f"  weak_evidence_override={body.get('weak_evidence_override')}")
                    print(f"  snapshot_id={body.get('snapshot_id')}")
                    print(f"  writeback_artifacts={body.get('writeback_artifacts', {})}")
                elif status == 409:
                    print(f"  写回被拒绝: {body}")
                else:
                    print(f"  错误: {body}")
        except Exception as e:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] 写回失败: {e}")

        # 8. 记录写回后状态
        print(f"\n=== 写回后状态 ===")
        after = await snapshot(session, headers, book_id)

        # 9. 对比写回前后
        print(f"\n=== 写回前后对比 ===")
        compare("characters", before.get("characters", []), after.get("characters", []))
        compare("world_entries", before.get("world_entries", []), after.get("world_entries", []))
        compare("outline_text", before.get("outline_text", ""), after.get("outline_text", ""))

        print(f"\n=== 测试用户保留: {username} (id={user_id}) ===")


async def snapshot(session, headers, book_id):
    """获取书籍的当前状态快照。"""
    result = {"characters": [], "world_entries": [], "outline_text": ""}
    try:
        async with session.get(f"{BASE}/api/workspace/books/{book_id}/characters", headers=headers) as r:
            data = await r.json()
            result["characters"] = data.get("items", data if isinstance(data, list) else [])
    except Exception:
        pass
    try:
        async with session.get(f"{BASE}/api/workspace/books/{book_id}/world", headers=headers) as r:
            data = await r.json()
            result["world_entries"] = data.get("items", data if isinstance(data, list) else [])
    except Exception:
        pass
    try:
        async with session.get(f"{BASE}/api/workspace/books/{book_id}", headers=headers) as r:
            data = await r.json()
            result["outline_text"] = str(data.get("outline_text", "") or "")
            result["title"] = data.get("title", "")
    except Exception:
        pass
    print(f"  characters={len(result['characters'])} world_entries={len(result['world_entries'])} "
          f"outline_len={len(result['outline_text'])}")
    return result


def compare(name, before, after):
    """对比写回前后的数据。"""
    if isinstance(before, list) and isinstance(after, list):
        delta = len(after) - len(before)
        sign = "+" if delta >= 0 else ""
        print(f"  {name}: {len(before)} -> {len(after)} ({sign}{delta})")
    elif isinstance(before, str) and isinstance(after, str):
        delta = len(after) - len(before)
        sign = "+" if delta >= 0 else ""
        print(f"  {name}: {len(before)} chars -> {len(after)} chars ({sign}{delta})")
    else:
        print(f"  {name}: before={type(before).__name__} after={type(after).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
