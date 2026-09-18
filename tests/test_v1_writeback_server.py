"""
V1 一次性分析 + 卡片写回测试（服务器端，纯标准库，同步）。
直接连接 127.0.0.1:8787，绕过 Nginx 60s 超时。
"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8787"


def api(method, path, *, token=None, body=None, timeout=3600):
    """同步 HTTP 调用。"""
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = {"raw": str(e)}
        return e.code, err_body


def snapshot(token, book_id):
    """获取书籍当前状态。"""
    result = {"characters": [], "world_entries": [], "outline_text": ""}
    try:
        _, data = api("GET", f"/api/workspace/books/{book_id}/characters", token=token, timeout=30)
        result["characters"] = data.get("items", data if isinstance(data, list) else [])
    except Exception:
        pass
    try:
        _, data = api("GET", f"/api/workspace/books/{book_id}/world", token=token, timeout=30)
        result["world_entries"] = data.get("items", data if isinstance(data, list) else [])
    except Exception:
        pass
    try:
        _, data = api("GET", f"/api/workspace/books/{book_id}", token=token, timeout=30)
        result["outline_text"] = str(data.get("outline_text", "") or "")
        result["title"] = data.get("title", "")
    except Exception:
        pass
    print(f"  characters={len(result['characters'])} world_entries={len(result['world_entries'])} "
          f"outline_len={len(result['outline_text'])}")
    return result


def compare(name, before, after):
    if isinstance(before, list) and isinstance(after, list):
        delta = len(after) - len(before)
        sign = "+" if delta >= 0 else ""
        print(f"  {name}: {len(before)} -> {len(after)} ({sign}{delta})")
    elif isinstance(before, str) and isinstance(after, str):
        delta = len(after) - len(before)
        sign = "+" if delta >= 0 else ""
        print(f"  {name}: {len(before)} chars -> {len(after)} chars ({sign}{delta})")


def main():
    # 1. 注册
    stamp = int(time.time())
    username = f"v1_srv_{stamp}"
    print(f"\n=== 注册测试用户: {username} ===")
    status, data = api("POST", "/api/auth/register",
                       body={"username": username, "password": "V1Srv1234", "is_author": False}, timeout=30)
    token = data.get("access_token", "")
    user_id = data.get("user", {}).get("id", 0)
    print(f"  user_id={user_id} token={'OK' if token else 'MISSING'}")
    if not token or not user_id:
        print("注册失败，退出")
        return

    # 2. AI 配置
    print(f"\n=== 设置 AI 配置 ===")
    ai_config = {
        "remote_enabled": True, "provider": "deepseek",
        "api_key": os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
        "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash",
        "temperature": 0.7, "max_tokens": 4096,
        "thinking_enabled": False, "thinking_budget_tokens": 10000,
        "interval_seconds": 8, "auto_write_threshold": 0.55, "probe_enabled": False,
    }
    profiles = {p: ai_config for p in ["book_analysis", "writing", "outline", "detector",
                                        "correction", "import", "skills", "review", "chat", "writing_probe"]}
    status, _ = api("PUT", "/api/settings/ai", token=token, body={"profiles": profiles}, timeout=30)
    print(f"  PUT /api/settings/ai: {status}")

    # 3. 获取范例书籍
    print(f"\n=== 获取范例书籍 ===")
    status, data = api("GET", "/api/workspace/books", token=token, timeout=30)
    items = data.get("items", [])
    if not items:
        print("  无书籍，退出")
        return
    book_id = int(items[0]["id"])
    print(f"  book_id={book_id} title={items[0].get('title', '')[:30]}")

    # 4. 写回前状态
    print(f"\n=== 写回前状态 ===")
    before = snapshot(token, book_id)

    # 5. V1 一次性分析
    print(f"\n=== V1 一次性分析 (可能需要 5-15 分钟) ===")
    start = time.time()
    try:
        status, body = api("POST", f"/api/workspace/books/{book_id}/analysis-v1/one-shot",
                           token=token, body={}, timeout=3000)
    except Exception as e:
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] 分析失败: {e}")
        return
    elapsed = int(time.time() - start)
    print(f"  [{elapsed}s] HTTP {status}")
    if status != 200:
        print(f"  错误: {body}")
        return
    run_id = int(body.get("run_id", 0) or body.get("item", {}).get("id", 0))
    item = body.get("item", body)
    print(f"  run_id={run_id} card_count={item.get('card_count', '?')} "
          f"draft_count={item.get('draft_count', '?')} status={item.get('status', '?')}")
    if not run_id:
        print("  未获得 run_id，退出")
        return

    # 6. 卡片列表
    print(f"\n=== 分析卡片列表 ===")
    status, data = api("GET", f"/api/workspace/analysis/runs/{run_id}/cards", token=token, timeout=30)
    cards = data.get("items", [])
    print(f"  共 {len(cards)} 张卡片:")
    for c in cards:
        ctype = c.get("card_type", "")
        st = c.get("status", "")
        score = c.get("ars_score", 0)
        uid = c.get("card_uid", "")[:30]
        pkeys = list((c.get("payload") or {}).keys())[:5]
        print(f"    [{ctype}] {uid} score={score} status={st} keys={pkeys}")
    if not cards:
        print("  无卡片，退出")
        return

    # 7. 写回
    print(f"\n=== 写回 (POST /analysis/runs/{run_id}/apply) ===")
    start = time.time()
    try:
        status, body = api("POST", f"/api/workspace/analysis/runs/{run_id}/apply",
                           token=token, body={}, timeout=600)
    except Exception as e:
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] 写回失败: {e}")
        body = None
    if body is not None:
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] HTTP {status}")
        if status == 200:
            print(f"  ok={body.get('ok')}")
            print(f"  applied_cards={body.get('applied_cards')}")
            print(f"  skipped_cards={body.get('skipped_cards')}")
            print(f"  updated_chapter_ids={body.get('updated_chapter_ids', [])[:10]}")
            print(f"  unresolved_count={body.get('unresolved_count')}")
            print(f"  evidence_gate_dropped={body.get('evidence_gate_dropped')}")
            print(f"  weak_evidence_override={body.get('weak_evidence_override')}")
            print(f"  snapshot_id={body.get('snapshot_id')}")
            wa = body.get("writeback_artifacts", {})
            if isinstance(wa, dict):
                print(f"  writeback_artifacts keys={list(wa.keys())}")
            else:
                print(f"  writeback_artifacts={wa}")
        elif status == 409:
            print(f"  写回被拒绝(证据不足): {body}")
        else:
            print(f"  错误: {body}")

    # 8. 写回后状态
    print(f"\n=== 写回后状态 ===")
    after = snapshot(token, book_id)

    # 9. 对比
    print(f"\n=== 写回前后对比 ===")
    compare("characters", before.get("characters", []), after.get("characters", []))
    compare("world_entries", before.get("world_entries", []), after.get("world_entries", []))
    compare("outline_text", before.get("outline_text", ""), after.get("outline_text", ""))

    # 10. 新增人物
    after_chars = after.get("characters", [])
    before_count = len(before.get("characters", []))
    if len(after_chars) > before_count:
        print(f"\n=== 新增人物 ({len(after_chars) - before_count} 个) ===")
        for c in after_chars[before_count:]:
            name = c.get("name", c.get("character_name", "?"))
            role = c.get("role", "")
            desc = str(c.get("description", c.get("profile_text", "")))[:60]
            print(f"  - {name} ({role}): {desc}")

    print(f"\n=== 测试用户保留: {username} (id={user_id}) ===")


if __name__ == "__main__":
    main()
