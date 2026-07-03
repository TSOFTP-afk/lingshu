"""
V3 AI 分析完整测试 — 复用用户 30 的 AI 配置，克隆到测试用户后运行 AI 模式分析。

测试流程:
1. 注册测试用户
2. 克隆用户 30 的 AI 配置到测试用户
3. 获取范例书籍
4. WebSocket 运行 V3 AI 分析（use_ai=True）
5. 记录所有 progress 消息
6. 验证最终结果
7. 清理测试用户
"""
import asyncio
import json
import time
import aiohttp

BASE = "https://www.ling-shu.top"
WS_BASE = "wss://www.ling-shu.top"
TEMPLATE_USER_ID = 30  # 用户 004，有完整 AI 配置


async def main():
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. 注册测试用户
        stamp = int(time.time())
        username = f"ai_test_{stamp}"
        password = "AiTest1234"
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

        # 2. 克隆 AI 配置（通过 API 设置）
        print(f"\n=== 克隆 AI 配置 from user {TEMPLATE_USER_ID} ===")
        # 先在服务器直接克隆 AI 配置
        # 使用 PUT /api/settings/ai 设置每个 purpose
        # 但我们不知道明文 api_key，所以直接在服务器数据库操作
        # 改为通过 API 设置（使用已知 API key）
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

        # PUT /api/settings/ai 需要 profiles 字典结构
        profiles = {}
        for purpose in ["book_analysis", "writing", "outline", "detector", "correction",
                        "import", "skills", "review", "chat", "writing_probe"]:
            profiles[purpose] = ai_config

        async with session.put(f"{BASE}/api/settings/ai",
                               json={"profiles": profiles},
                               headers=headers) as r:
            status = r.status
            body = await r.text()
            print(f"  PUT /api/settings/ai: {status} {body[:200]}")
        print("  AI 配置设置完成")

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

        # 4. WebSocket 运行 V3 AI 分析
        print(f"\n=== V3 AI 分析 (use_ai=True) ===")
        print(f"  这可能需要 10-30 分钟，请耐心等待...")
        run_id = 0
        progress_messages = []
        try:
            run_id = await test_v3_ws(session, token, book_id, use_ai=True, timeout_sec=1800, progress_messages=progress_messages)
        except Exception as e:
            print(f"\n  分析失败: {e}")

        # 5. 结果汇总
        print(f"\n=== 结果 ===")
        print(f"  run_id: {run_id}")
        print(f"  progress 消息数: {len(progress_messages)}")
        if progress_messages:
            print(f"  最后进度: {progress_messages[-1]}")

        if run_id:
            # 验证分析结果
            print(f"\n=== 验证分析结果 ===")
            for endpoint in ["blocks", "mentions", "entities", "facts", "cards", "events"]:
                try:
                    async with session.get(f"{BASE}/api/workspace/analysis-v3/runs/{run_id}/{endpoint}", headers=headers) as r:
                        data = await r.json()
                        items = data if isinstance(data, list) else data.get("items", [])
                        print(f"  {endpoint}: {len(items)} 条")
                except Exception as e:
                    print(f"  {endpoint}: ERROR {e}")

            try:
                async with session.get(f"{BASE}/api/workspace/analysis-v3/runs/{run_id}/probes/plans", headers=headers) as r:
                    data = await r.json()
                    items = data if isinstance(data, list) else data.get("items", [])
                    print(f"  probes/plans: {len(items)} 条")
            except Exception as e:
                print(f"  probes/plans: ERROR {e}")

        # 6. 清理 - 不删除测试用户（保留用于排查）
        print(f"\n=== 测试用户保留用于排查: {username} (id={user_id}) ===")


async def test_v3_ws(session, token, book_id, *, use_ai, timeout_sec=1800, progress_messages=None):
    """通过 WebSocket 运行 V3 分析，返回 run_id。"""
    ws_url = f"{WS_BASE}/ws/analysis-v3"
    task_id = f"ai-test-{int(time.time())}"
    deadline = time.time() + timeout_sec

    async with session.ws_connect(ws_url, heartbeat=None, timeout=15) as ws:
        await ws.send_json({"type": "auth", "payload": {"token": token}})

        auth_ok = False
        analyze_sent = False
        run_id = 0
        last_progress_time = time.time()
        start_time = time.time()

        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
            except asyncio.TimeoutError:
                elapsed = int(time.time() - start_time)
                since_progress = int(time.time() - last_progress_time)
                if time.time() - last_progress_time > 300:
                    print(f"  [{elapsed}s] WARNING: 300 秒无进度更新 (last progress {since_progress}s ago)")
                if time.time() - last_progress_time > 600:
                    raise RuntimeError(f"V3 分析 600 秒无进度更新")
                continue

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                mtype = data.get("type", "")

                if mtype == "ping":
                    await ws.send_json({"type": "pong"})
                    continue

                if mtype == "auth_ok" and not analyze_sent:
                    auth_ok = True
                    last_progress_time = time.time()
                    await ws.send_json({
                        "type": "analyze_v3",
                        "task_id": task_id,
                        "payload": {"book_id": book_id, "use_ai": use_ai},
                    })
                    analyze_sent = True
                    print(f"  [0s] analyze_v3 sent (use_ai={use_ai})")
                    continue

                if data.get("task_id") != task_id and mtype != "ping":
                    continue

                elapsed = int(time.time() - start_time)

                if mtype == "analysis_v3.progress":
                    last_progress_time = time.time()
                    payload = data.get("payload", {})
                    percent = payload.get("percent", 0)
                    message = payload.get("message", "")
                    stage = payload.get("stage", "")
                    print(f"  [{elapsed}s] {percent}% [{stage}] {message[:60]}")
                    if progress_messages is not None:
                        progress_messages.append({"elapsed": elapsed, "percent": percent, "stage": stage, "message": message})

                elif mtype == "analysis_v3.result":
                    payload = data.get("payload", {})
                    if payload.get("status") == "ok":
                        run_id = int(payload.get("run_id", 0))
                        print(f"  [{elapsed}s] RESULT OK run_id={run_id}")
                        print(f"    blocks={payload.get('block_count')} mentions={payload.get('mention_count')} "
                              f"entities={payload.get('entity_count')} facts={payload.get('fact_count')} "
                              f"cards={payload.get('card_count')}")
                    else:
                        print(f"  [{elapsed}s] RESULT {payload.get('status')}")
                    break

                elif mtype == "analysis_v3.error":
                    payload = data.get("payload", {})
                    print(f"  [{elapsed}s] ERROR: {payload.get('message', 'unknown')}")
                    raise RuntimeError(f"V3 分析错误: {payload.get('message', 'unknown')}")

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                raise RuntimeError(f"WebSocket 连接关闭 (type={msg.type})")

        if not auth_ok:
            raise RuntimeError("WebSocket 认证失败")
        return run_id


if __name__ == "__main__":
    asyncio.run(main())
