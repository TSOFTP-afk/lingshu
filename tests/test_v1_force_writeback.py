"""强制写回 V1 分析结果（user_override=True），绕过 evidence gate。"""
import json
import urllib.request
import urllib.error

if __name__ != "__main__":
    # 导入期安全护栏：本文件被 pytest 收集时会在导入期直连服务器执行写回。
    # 直接运行 `python tests/test_v1_force_writeback.py` 不受影响。
    import pytest

    pytestmark = pytest.mark.runtime
    pytest.skip(
        "强制写回为真实环境验证脚本（导入期执行副作用），默认收集时跳过",
        allow_module_level=True,
    )

BASE = "http://127.0.0.1:8787"
USERNAME = "v1_srv_1782911020"
PASSWORD = "V1Srv1234"
RUN_ID = 81
BOOK_ID = 49


def api(method, path, *, token=None, body=None, timeout=600):
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
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"raw": str(e)}


# 登录
_, data = api("POST", "/api/auth/login", body={"username": USERNAME, "password": PASSWORD}, timeout=30)
token = data.get("access_token", "")
print(f"登录: token={'OK' if token else 'FAIL'}")

# 写回前快照
_, before_chars = api("GET", f"/api/workspace/books/{BOOK_ID}/characters", token=token, timeout=30)
before_c = len(before_chars.get("items", []))
_, before_world = api("GET", f"/api/workspace/books/{BOOK_ID}/world", token=token, timeout=30)
before_w = len(before_world.get("items", []))
_, before_book = api("GET", f"/api/workspace/books/{BOOK_ID}", token=token, timeout=30)
before_o = len(str(before_book.get("outline_text", "") or ""))
print(f"写回前: characters={before_c} world={before_w} outline={before_o}")

# 强制写回
print(f"\n=== 强制写回 run_id={RUN_ID} (user_override=True) ===")
status, body = api("POST", f"/api/workspace/analysis/runs/{RUN_ID}/apply",
                   token=token, body={"user_override": True}, timeout=600)
print(f"HTTP {status}")
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
    print(f"  错误: {json.dumps(body, ensure_ascii=False, indent=2)}")

# 写回后快照
_, after_chars = api("GET", f"/api/workspace/books/{BOOK_ID}/characters", token=token, timeout=30)
after_c = len(after_chars.get("items", []))
_, after_world = api("GET", f"/api/workspace/books/{BOOK_ID}/world", token=token, timeout=30)
after_w = len(after_world.get("items", []))
_, after_book = api("GET", f"/api/workspace/books/{BOOK_ID}", token=token, timeout=30)
after_o = len(str(after_book.get("outline_text", "") or ""))
print(f"\n写回后: characters={after_c} world={after_w} outline={after_o}")
print(f"变化: characters {before_c}->{after_c} ({after_c-before_c:+d}), "
      f"world {before_w}->{after_w} ({after_w-before_w:+d}), "
      f"outline {before_o}->{after_o} ({after_o-before_o:+d})")

# 显示新增人物
if after_c > before_c:
    items = after_chars.get("items", [])
    print(f"\n=== 新增人物 ({after_c-before_c} 个) ===")
    for c in items[before_c:]:
        name = c.get("name", c.get("character_name", "?"))
        role = c.get("role", "")
        desc = str(c.get("description", c.get("profile_text", "")))[:80]
        print(f"  - {name} ({role}): {desc}")

# 显示新增世界观
if after_w > before_w:
    items = after_world.get("items", [])
    print(f"\n=== 新增世界观 ({after_w-before_w} 个) ===")
    for w in items[before_w:]:
        name = w.get("name", w.get("entry_name", "?"))
        category = w.get("category", "")
        desc = str(w.get("description", w.get("content_text", "")))[:80]
        print(f"  - {name} ({category}): {desc}")
