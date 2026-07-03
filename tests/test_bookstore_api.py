from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel_app.bookstore import BookstoreStore, client_password_hash, create_app
from novel_app.bookstore.security import legacy_public_client_password_hash

PUBLISH_TOKEN = "test-publish-token"


def _payload(**overrides):
    data = {
        "source_app": "lingshu-desktop",
        "source_book_id": 12,
        "source_volume_id": 3,
        "source_chapter_id": 45,
        "book_title": "镜湖试读",
        "volume_title": "第一卷",
        "chapter_title": "第一章 风起",
        "sort_order": 1,
        "outline": "主角抵达镜湖。",
        "summary_text": "镜湖边的第一场冲突。",
        "content": "风从湖面吹来，少年第一次看见城墙后的光。",
        "ai_probability": 12,
        "ai_probability_level": "low",
        "updated_at": "2026-06-02 12:00:00",
    }
    data.update(overrides)
    return data


def _client(tmp_path: Path, **kwargs) -> TestClient:
    return TestClient(create_app(db_path=tmp_path / "bookstore.db", publish_token=PUBLISH_TOKEN, **kwargs))


def _publish(client: TestClient, **overrides):
    return client.post(
        "/api/publish/chapter",
        json=_payload(**overrides),
        headers={"X-Publish-Token": PUBLISH_TOKEN},
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user_client(tmp_path: Path, username: str = "author", password: str = "pw", is_author: int = 1) -> tuple[TestClient, dict]:
    db_path = tmp_path / f"{username}.db"
    app = create_app(db_path=db_path, publish_token=PUBLISH_TOKEN)
    user = BookstoreStore(db_path).create_user(username, password, is_author=is_author)
    return TestClient(app), user


def test_publish_chapter_creates_book_and_readable_chapter(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = _publish(client)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["book_id"] == 1
    assert body["chapter_id"] == 1
    assert "/books/1/chapters/1" in body["web_url"]

    books = client.get("/api/books").json()["items"]
    assert len(books) == 1
    assert books[0]["title"] == "镜湖试读"
    assert books[0]["chapter_count"] == 1

    chapter = client.get("/api/chapters/1").json()
    assert chapter["book_title"] == "镜湖试读"
    assert chapter["title"] == "第一章 风起"
    assert chapter["previous_chapter_id"] is None
    assert chapter["next_chapter_id"] is None


def test_publish_chapter_is_idempotent_by_source_ids(tmp_path: Path) -> None:
    client = _client(tmp_path)

    first = _publish(client).json()
    second = _publish(client, chapter_title="第一章 风再起", content="修改后的章节正文。").json()

    assert first["book_id"] == second["book_id"]
    assert first["chapter_id"] == second["chapter_id"]
    chapters = client.get("/api/books/1/chapters").json()["items"]
    assert len(chapters) == 1
    assert chapters[0]["title"] == "第一章 风再起"
    assert client.get("/api/chapters/1").json()["content"] == "修改后的章节正文。"


def test_chapter_order_and_previous_next_links(tmp_path: Path) -> None:
    client = _client(tmp_path)

    _publish(client, source_chapter_id=2, chapter_title="第二章", sort_order=2)
    _publish(client, source_chapter_id=1, chapter_title="第一章", sort_order=1)

    chapters = client.get("/api/books/1/chapters").json()["items"]
    assert [item["title"] for item in chapters] == ["第一章", "第二章"]
    first = client.get(f"/api/chapters/{chapters[0]['id']}").json()
    second = client.get(f"/api/chapters/{chapters[1]['id']}").json()
    assert first["next_chapter_id"] == second["id"]
    assert second["previous_chapter_id"] == first["id"]


def test_book_search_escapes_like_wildcards(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _publish(client, source_book_id=1, source_chapter_id=1, book_title="普通书名")
    _publish(client, source_book_id=2, source_chapter_id=1, book_title="另一部作品")

    assert client.get("/api/books", params={"q": "%"}).json()["items"] == []
    assert client.get("/api/books", params={"q": "_"}).json()["items"] == []


def test_publish_rejects_blank_content(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = _publish(client, content="   ")

    assert response.status_code == 422


def test_publish_token_is_required_and_enforced(tmp_path: Path) -> None:
    unconfigured = TestClient(create_app(db_path=tmp_path / "unconfigured.db"))
    assert unconfigured.post("/api/publish/chapter", json=_payload()).status_code == 503

    client = TestClient(create_app(db_path=tmp_path / "bookstore.db", publish_token="secret"))

    assert client.post("/api/publish/chapter", json=_payload()).status_code == 401
    assert client.post(
        "/api/publish/chapter",
        json=_payload(),
        headers={"X-Publish-Token": "wrong"},
    ).status_code == 401
    assert client.post(
        "/api/publish/chapter",
        json=_payload(),
        headers={"X-Publish-Token": "secret"},
    ).status_code == 200


def test_health_does_not_expose_database_path(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/health").json() == {"ok": True}


def test_login_accepts_plain_and_client_hashed_passwords(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")

    plain = client.post("/api/auth/login", json={"username": "author", "password": "pw"})
    hashed = client.post(
        "/api/auth/login",
        json={"username": "author", "password": client_password_hash("pw")},
    )

    assert plain.status_code == 200
    assert hashed.status_code == 200


def test_login_accepts_legacy_public_client_hash_accounts(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password=legacy_public_client_password_hash("pw"))

    plain = client.post("/api/auth/login", json={"username": "author", "password": "pw"})

    assert plain.status_code == 200


def test_web_author_publish_uses_bearer_user_and_overrides_source_app(tmp_path: Path) -> None:
    client, user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]

    response = client.post(
        "/api/publish/chapter",
        json=_payload(source_app="user_999", source_book_id="web-draft-1"),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    books = client.get("/api/author/books", headers={"Authorization": f"Bearer {token}"}).json()["items"]
    assert len(books) == 1
    assert books[0]["source_app"] == f"user_{user['id']}"
    assert books[0]["source_book_id"] == "web-draft-1"


def test_author_can_create_empty_book_from_profile(tmp_path: Path) -> None:
    client, user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]

    response = client.post(
        "/api/author/books",
        json={"title": "新书", "summary": "第一版简介", "sub_tags": "玄幻，升级 爽文"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    item = response.json()["item"]
    assert item["title"] == "新书"
    assert item["summary"] == "第一版简介"
    assert item["source_app"] == f"user_{user['id']}"
    assert item["sub_tags"] == "玄幻,升级,爽文"
    assert item["chapter_count"] == 0
    assert item["word_count"] == 0

    books = client.get("/api/author/books", headers={"Authorization": f"Bearer {token}"}).json()["items"]
    assert len(books) == 1
    assert books[0]["id"] == item["id"]


def test_reader_cannot_create_author_book(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, username="reader", password="pw", is_author=0)
    token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]

    response = client.post(
        "/api/author/books",
        json={"title": "不该创建"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_author_updates_only_own_book_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.db"
    app = create_app(db_path=db_path, publish_token=PUBLISH_TOKEN)
    store = BookstoreStore(db_path)
    store.create_user("author_a", "pw", is_author=1)
    store.create_user("author_b", "pw", is_author=1)
    client = TestClient(app)
    token_a = client.post("/api/auth/login", json={"username": "author_a", "password": "pw"}).json()["access_token"]
    token_b = client.post("/api/auth/login", json={"username": "author_b", "password": "pw"}).json()["access_token"]

    created = client.post(
        "/api/author/books",
        json={"title": "可编辑作品", "summary": "旧简介"},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()["item"]

    forbidden = client.patch(
        f"/api/author/books/{created['id']}",
        json={"summary": "越权简介"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    updated = client.patch(
        f"/api/author/books/{created['id']}",
        json={"summary": "新的简介"},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert forbidden.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["item"]["summary"] == "新的简介"
    books = client.get("/api/author/books", headers={"Authorization": f"Bearer {token_a}"}).json()["items"]
    assert books[0]["summary"] == "新的简介"


def test_author_can_create_next_chapter_for_empty_book(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    book = client.post(
        "/api/author/books",
        json={"title": "空书草稿"},
        headers=headers,
    ).json()["item"]

    response = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers)

    assert response.status_code == 200
    item = response.json()["item"]
    assert item["title"] == "第1章 未命名"
    assert item["volume_title"] == "正文"
    assert item["sort_order"] == 1
    assert item["content"] == ""
    assert item["word_count"] == 0
    assert item["status"] == "draft"
    assert item["published_at"] == ""

    chapters = client.get(f"/api/author/books/{book['id']}/chapters", headers=headers).json()["items"]
    assert len(chapters) == 1
    assert chapters[0]["status"] == "draft"
    assert chapters[0]["published_at"] == ""
    assert chapters[0]["title"] == "第1章 未命名"


def test_author_next_chapter_increments_and_reuses_volume(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    book = client.post("/api/author/books", json={"title": "连载草稿"}, headers=headers).json()["item"]
    first = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers).json()["item"]
    client.patch(
        f"/api/author/books/{book['id']}/chapters/{first['id']}",
        json={"title": "第一章 起笔", "volume_title": "第一卷", "content": "开篇。"},
        headers=headers,
    )

    second = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers)

    assert second.status_code == 200
    item = second.json()["item"]
    assert item["title"] == "第2章 未命名"
    assert item["volume_title"] == "第一卷"
    assert item["sort_order"] == 2
    chapters = client.get(f"/api/author/books/{book['id']}/chapters", headers=headers).json()["items"]
    assert [chapter["sort_order"] for chapter in chapters] == [1, 2]


def test_author_can_update_and_delete_own_chapter(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    book = client.post("/api/author/books", json={"title": "可编辑章节"}, headers=headers).json()["item"]
    chapter = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers).json()["item"]

    updated = client.patch(
        f"/api/author/books/{book['id']}/chapters/{chapter['id']}",
        json={"title": "第二稿标题", "volume_title": "第二卷", "content": "新的正文\n第二段"},
        headers=headers,
    )
    read_back = client.get(f"/api/author/books/{book['id']}/chapters/{chapter['id']}", headers=headers)
    deleted = client.delete(f"/api/author/books/{book['id']}/chapters/{chapter['id']}", headers=headers)

    assert updated.status_code == 200
    assert updated.json()["item"]["title"] == "第二稿标题"
    assert updated.json()["item"]["volume_title"] == "第二卷"
    assert updated.json()["item"]["word_count"] == len("新的正文\n第二段")
    assert read_back.status_code == 200
    assert read_back.json()["content"] == "新的正文\n第二段"
    assert deleted.status_code == 200
    chapters = client.get(f"/api/author/books/{book['id']}/chapters", headers=headers).json()["items"]
    assert chapters == []


def test_author_draft_is_hidden_until_published(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    book = client.post("/api/author/books", json={"title": "待发布作品"}, headers=headers).json()["item"]
    chapter = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers).json()["item"]

    empty_publish = client.post(f"/api/author/books/{book['id']}/chapters/{chapter['id']}/publish", headers=headers)
    client.patch(
        f"/api/author/books/{book['id']}/chapters/{chapter['id']}",
        json={"title": "第一章 正式开篇", "volume_title": "正文", "content": "发布后的正文。"},
        headers=headers,
    )
    before_books = client.get("/api/books").json()["items"]
    before_chapters = client.get(f"/api/books/{book['id']}/chapters").json()["items"]
    before_reader = client.get(f"/api/chapters/{chapter['id']}")

    published = client.post(f"/api/author/books/{book['id']}/chapters/{chapter['id']}/publish", headers=headers)
    after_books = client.get("/api/books").json()["items"]
    after_chapters = client.get(f"/api/books/{book['id']}/chapters").json()["items"]
    after_reader = client.get(f"/api/chapters/{chapter['id']}")

    assert empty_publish.status_code == 422
    assert before_books[0]["chapter_count"] == 0
    assert before_books[0]["latest_chapter_title"] is None
    assert before_chapters == []
    assert before_reader.status_code == 404
    assert published.status_code == 200
    assert published.json()["item"]["status"] == "published"
    assert published.json()["item"]["published_at"]
    assert after_books[0]["chapter_count"] == 1
    assert after_books[0]["latest_chapter_title"] == "第一章 正式开篇"
    assert after_chapters[0]["status"] == "published"
    assert after_reader.status_code == 200
    assert after_reader.json()["title"] == "第一章 正式开篇"


def test_author_chapter_routes_require_author_and_ownership(tmp_path: Path) -> None:
    db_path = tmp_path / "shared-chapters.db"
    app = create_app(db_path=db_path, publish_token=PUBLISH_TOKEN)
    store = BookstoreStore(db_path)
    store.create_user("author_a", "pw", is_author=1)
    store.create_user("author_b", "pw", is_author=1)
    store.create_user("reader", "pw", is_author=0)
    client = TestClient(app)
    token_a = client.post("/api/auth/login", json={"username": "author_a", "password": "pw"}).json()["access_token"]
    token_b = client.post("/api/auth/login", json={"username": "author_b", "password": "pw"}).json()["access_token"]
    reader_token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]
    headers_a = _auth_headers(token_a)
    headers_b = _auth_headers(token_b)
    reader_headers = _auth_headers(reader_token)
    book = client.post("/api/author/books", json={"title": "私有作品"}, headers=headers_a).json()["item"]
    chapter = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers_a).json()["item"]

    assert client.get(f"/api/author/books/{book['id']}/chapters", headers=reader_headers).status_code == 403
    assert client.post(f"/api/author/books/{book['id']}/chapters/next", headers=reader_headers).status_code == 403
    assert client.get(f"/api/author/books/{book['id']}/chapters", headers=headers_b).status_code == 404
    assert client.get(f"/api/author/books/{book['id']}/chapters/{chapter['id']}", headers=headers_b).status_code == 404
    assert client.patch(
        f"/api/author/books/{book['id']}/chapters/{chapter['id']}",
        json={"title": "越权", "volume_title": "正文", "content": "不应保存"},
        headers=headers_b,
    ).status_code == 404
    assert client.delete(f"/api/author/books/{book['id']}/chapters/{chapter['id']}", headers=headers_b).status_code == 404
    assert len(client.get(f"/api/author/books/{book['id']}/chapters", headers=headers_a).json()["items"]) == 1


def test_bookshelf_requires_login(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/bookshelf").status_code == 401
    assert client.put("/api/bookshelf/1").status_code == 401
    assert client.patch("/api/bookshelf/1/progress", json={"chapter_id": 1}).status_code == 401


def test_user_can_add_query_and_remove_bookshelf_item(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, username="reader", password="pw", is_author=0)
    token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    _publish(client)

    added = client.put("/api/bookshelf/1", headers=headers)
    repeated = client.put("/api/bookshelf/1", headers=headers)
    status = client.get("/api/bookshelf/1", headers=headers)
    listed = client.get("/api/bookshelf", headers=headers)
    removed = client.delete("/api/bookshelf/1", headers=headers)
    after_remove = client.get("/api/bookshelf/1", headers=headers)

    assert added.status_code == 200
    assert repeated.status_code == 200
    assert status.json()["in_shelf"] is True
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["title"] == "镜湖试读"
    assert listed.json()["items"][0]["first_chapter_id"] == 1
    assert listed.json()["items"][0]["latest_chapter_id"] == 1
    assert listed.json()["items"][0]["progress_percent"] == 0
    assert removed.status_code == 200
    assert after_remove.json()["in_shelf"] is False


def test_user_can_create_custom_bookshelf(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, username="reader", password="pw", is_author=0)
    token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    _publish(client)
    client.put("/api/bookshelf/1", headers=headers)

    shelves = client.get("/api/bookshelf/shelves", headers=headers)
    created = client.post("/api/bookshelf/shelves", json={"name": "追更书架"}, headers=headers)
    repeated = client.post("/api/bookshelf/shelves", json={"name": "追更书架"}, headers=headers)
    default_items = client.get("/api/bookshelf", headers=headers)
    custom_items = client.get(f"/api/bookshelf?shelf_id={created.json()['item']['id']}", headers=headers)

    assert shelves.status_code == 200
    assert shelves.json()["items"][0]["name"] == "檀墨书箱"
    assert shelves.json()["items"][0]["book_count"] == 1
    assert created.status_code == 200
    assert created.json()["item"]["name"] == "追更书架"
    assert created.json()["item"]["book_count"] == 0
    assert repeated.status_code == 409
    assert len(default_items.json()["items"]) == 1
    assert custom_items.json()["items"] == []

def test_bookshelf_is_private_per_user(tmp_path: Path) -> None:
    db_path = tmp_path / "private-shelf.db"
    app = create_app(db_path=db_path, publish_token=PUBLISH_TOKEN)
    store = BookstoreStore(db_path)
    store.create_user("reader_a", "pw", is_author=0)
    store.create_user("reader_b", "pw", is_author=0)
    client = TestClient(app)
    token_a = client.post("/api/auth/login", json={"username": "reader_a", "password": "pw"}).json()["access_token"]
    token_b = client.post("/api/auth/login", json={"username": "reader_b", "password": "pw"}).json()["access_token"]
    _publish(client)

    assert client.put("/api/bookshelf/1", headers=_auth_headers(token_a)).status_code == 200
    assert len(client.get("/api/bookshelf", headers=_auth_headers(token_a)).json()["items"]) == 1
    assert client.get("/api/bookshelf/1", headers=_auth_headers(token_b)).json()["in_shelf"] is False
    assert client.patch("/api/bookshelf/1/progress", json={"chapter_id": 1}, headers=_auth_headers(token_b)).status_code == 404


def test_bookshelf_progress_requires_published_chapter_in_book(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    _publish(client, source_chapter_id=1, sort_order=1, chapter_title="第一章")
    _publish(client, source_chapter_id=2, sort_order=2, chapter_title="第二章")
    other = _publish(client, source_book_id=99, source_chapter_id=1, sort_order=1, chapter_title="别书章节").json()
    draft_book = client.post("/api/author/books", json={"title": "草稿书"}, headers=headers).json()["item"]
    draft = client.post(f"/api/author/books/{draft_book['id']}/chapters/next", headers=headers).json()["item"]

    client.put("/api/bookshelf/1", headers=headers)
    updated = client.patch("/api/bookshelf/1/progress", json={"chapter_id": 2}, headers=headers)
    wrong_book = client.patch("/api/bookshelf/1/progress", json={"chapter_id": other["chapter_id"]}, headers=headers)
    client.put(f"/api/bookshelf/{draft_book['id']}", headers=headers)
    draft_progress = client.patch(
        f"/api/bookshelf/{draft_book['id']}/progress",
        json={"chapter_id": draft["id"]},
        headers=headers,
    )

    assert updated.status_code == 200
    assert updated.json()["item"]["last_chapter_id"] == 2
    assert updated.json()["item"]["last_chapter_title"] == "第二章"
    assert updated.json()["item"]["progress_percent"] == 100
    assert wrong_book.status_code == 422
    assert draft_progress.status_code == 422


def test_reader_cannot_publish_with_bearer_token(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, username="reader", password="pw", is_author=0)
    token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]

    response = client.post(
        "/api/publish/chapter",
        json=_payload(source_app="user_999"),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_trusted_device_lifecycle(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, password="pw")
    token = client.post("/api/auth/login", json={"username": "author", "password": "pw"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"fingerprint": "fp-001", "device_info": "Windows / Chrome"}

    first = client.post("/api/auth/check-device", json=payload, headers=headers)
    trusted = client.post("/api/auth/trust-device", json=payload, headers=headers)
    second = client.post("/api/auth/check-device", json=payload, headers=headers)
    devices = client.get("/api/auth/devices", headers=headers)

    assert first.status_code == 200
    assert first.json()["trusted"] is False
    assert trusted.status_code == 200
    assert second.status_code == 200
    assert second.json()["trusted"] is True
    assert devices.status_code == 200
    assert devices.json()["items"][0]["fingerprint"] == "fp-001"


def test_admin_routes_require_login_and_admin(tmp_path: Path) -> None:
    client, _user = _create_user_client(tmp_path, username="reader", password="pw", is_author=0)
    token = client.post("/api/auth/login", json={"username": "reader", "password": "pw"}).json()["access_token"]

    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers=_auth_headers(token)).status_code == 403


def test_admin_env_grant_can_view_sanitized_user_and_token_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "admin.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))

    login = client.post("/api/auth/login", json={"username": "root", "password": "pw"})
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    assert login.status_code == 200
    assert login.json()["user"]["is_admin"] == 1
    users = client.get("/api/admin/users", headers=headers)
    tokens = client.get("/api/admin/tokens", headers=headers)

    assert users.status_code == 200
    assert users.json()["items"][0]["username"] == "root"
    assert "password_hash" not in users.json()["items"][0]
    assert tokens.status_code == 200
    token_item = tokens.json()["items"][0]
    assert "token" not in token_item
    assert token_item["token_hash"]
    assert token_item["token_preview"] != token


def test_cloud_usage_schema_migrates_old_auth_tokens_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-auth.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE auth_tokens (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at DATETIME NOT NULL)")
        connection.execute("INSERT INTO auth_tokens (token, user_id, expires_at) VALUES ('legacy-token', 1, datetime('now', '+1 day'))")

    BookstoreStore(db_path)
    BookstoreStore(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(auth_tokens)").fetchall()
        }
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        token_hash = connection.execute("SELECT token_hash FROM auth_tokens WHERE token = 'legacy-token'").fetchone()[0]

    assert {"created_at", "revoked_at", "token_hash"} <= columns
    assert {"book_fulltexts", "user_online_sessions", "user_analysis_runs", "user_ai_usage_events"} <= tables
    assert token_hash


def test_author_save_updates_fulltext_snapshot_and_anonymous_publish_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "fulltext.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    token = client.post("/api/auth/login", json={"username": "root", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)

    book = client.post("/api/author/books", json={"title": "Fulltext Book"}, headers=headers).json()["item"]
    first = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers).json()["item"]
    client.patch(
        f"/api/author/books/{book['id']}/chapters/{first['id']}",
        json={"title": "Chapter One", "volume_title": "Volume A", "content": "alpha body"},
        headers=headers,
    )
    second = client.post(f"/api/author/books/{book['id']}/chapters/next", headers=headers).json()["item"]
    client.patch(
        f"/api/author/books/{book['id']}/chapters/{second['id']}",
        json={"title": "Chapter Two", "volume_title": "Volume A", "content": "beta body"},
        headers=headers,
    )
    _publish(
        client,
        source_app="lingshu-desktop",
        source_book_id="anonymous-import",
        book_title="Anonymous Import",
        source_chapter_id="chapter-1",
        chapter_title="Imported",
        content="anonymous body",
    )

    detail = client.get(f"/api/admin/books/{book['id']}", headers=headers).json()
    overview = client.get("/api/admin/overview", headers=headers).json()["counts"]

    assert detail["fulltext_chapter_count"] == 2
    assert detail["fulltext_revision"] >= 3
    assert "# Chapter One" in detail["fulltext"]
    assert "alpha body" in detail["fulltext"]
    assert "beta body" in detail["fulltext"]
    assert overview["book_fulltexts"] == 1
    assert overview["book_fulltext_chars"] == detail["fulltext_char_count"]


def test_login_logout_records_online_session_and_revokes_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "online.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    login = client.post("/api/auth/login", json={"username": "root", "password": "pw"})
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    before_logout = client.get("/api/admin/users", headers=headers).json()["items"][0]
    logout = client.post("/api/auth/logout", headers=headers)

    assert before_logout["online_seconds"] >= 0
    assert logout.status_code == 200
    assert logout.json()["ok"] is True
    assert client.get("/api/admin/overview", headers=headers).status_code == 401

    with sqlite3.connect(db_path) as connection:
        session = connection.execute(
            "SELECT status, estimated_online_seconds FROM user_online_sessions"
        ).fetchone()
        token_row = connection.execute("SELECT revoked_at FROM auth_tokens").fetchone()

    assert session[0] == "logged_out"
    assert session[1] >= 0
    assert token_row[0] is not None


def test_admin_usage_summary_counts_analysis_ai_tokens_and_input_chars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "usage.db"
    store = BookstoreStore(db_path)
    user = store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    token = client.post("/api/auth/login", json={"username": "root", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)

    analysis_id = store.record_user_analysis_run(
        user_id=user["id"],
        analysis_mode="analysis_v3_l1",
        input_chars=120,
        source="test",
        run_ref="run-1",
    )
    store.record_user_ai_usage(
        user_id=user["id"],
        analysis_run_id=analysis_id,
        feature="polish_selection",
        model="test-model",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        token_source="provider",
        input_chars=40,
        output_chars=25,
        trace_id="trace-test-1",
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        latency_ms=123,
    )

    overview = client.get("/api/admin/overview", headers=headers).json()["counts"]
    user_item = client.get("/api/admin/users", headers=headers).json()["items"][0]
    user_detail = client.get(f"/api/admin/users/{user['id']}", headers=headers).json()
    quota = client.get("/api/admin/quotas", headers=headers).json()["items"][0]

    assert overview["analysis_runs"] == 1
    assert overview["ai_total_tokens"] == 18
    assert overview["total_input_chars"] == 160
    assert user_item["analysis_count"] == 1
    assert user_item["ai_total_tokens"] == 18
    assert user_item["total_input_chars"] == 160
    assert user_detail["usage_summary"]["analysis_count"] == 1
    assert user_detail["analysis_runs"][0]["run_ref"] == "run-1"
    assert user_detail["ai_usage_events"][0]["token_source"] == "provider"
    assert user_detail["ai_usage_events"][0]["trace_id"] == "trace-test-1"
    assert user_detail["ai_usage_events"][0]["prompt_version"] == "prompt-v1"
    assert user_detail["ai_usage_events"][0]["schema_version"] == "schema-v1"
    assert user_detail["ai_usage_events"][0]["latency_ms"] == 123
    assert quota["ai_calls_used"] == 1
    assert quota["ai_total_tokens"] == 18


def test_admin_soft_delete_book_hides_public_data_and_restore_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "admin-soft-delete.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    token = client.post("/api/auth/login", json={"username": "root", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    published = _publish(client, book_title="Visible Book", chapter_title="First", content="hello").json()

    deleted = client.delete(f"/api/admin/books/{published['book_id']}", headers=headers)
    public_books = client.get("/api/books")
    public_book = client.get(f"/api/books/{published['book_id']}")
    admin_books = client.get("/api/admin/books", headers=headers)
    audits = client.get("/api/admin/audit-logs", headers=headers)
    restored = client.post(f"/api/admin/books/{published['book_id']}/restore", headers=headers)

    assert deleted.status_code == 200
    assert public_books.json()["items"] == []
    assert public_book.status_code == 404
    assert admin_books.json()["items"][0]["deleted_at"]
    assert any(item["action"] == "delete" and item["object_type"] == "book" for item in audits.json()["items"])
    assert restored.status_code == 200
    assert client.get("/api/books").json()["items"][0]["title"] == "Visible Book"


def test_admin_soft_delete_chapter_hides_public_chapter_and_restore_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "admin-chapter-delete.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    token = client.post("/api/auth/login", json={"username": "root", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    published = _publish(client, book_title="Book", chapter_title="First", content="hello").json()

    deleted = client.delete(f"/api/admin/chapters/{published['chapter_id']}", headers=headers)
    public_chapters = client.get(f"/api/books/{published['book_id']}/chapters")
    public_chapter = client.get(f"/api/chapters/{published['chapter_id']}")
    admin_chapters = client.get("/api/admin/chapters", headers=headers)
    restored = client.post(f"/api/admin/chapters/{published['chapter_id']}/restore", headers=headers)

    assert deleted.status_code == 200
    assert public_chapters.json()["items"] == []
    assert public_chapter.status_code == 404
    assert admin_chapters.json()["items"][0]["deleted_at"]
    assert restored.status_code == 200
    assert client.get(f"/api/books/{published['book_id']}/chapters").json()["items"][0]["title"] == "First"


def test_admin_can_view_bookshelf_and_revoke_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "admin-bookshelf.db"
    store = BookstoreStore(db_path)
    store.create_user("root", "pw", is_author=1)
    monkeypatch.setenv("BOOKSTORE_ADMIN_USERS", "root")
    client = TestClient(create_app(db_path=db_path, publish_token=PUBLISH_TOKEN))
    token = client.post("/api/auth/login", json={"username": "root", "password": "pw"}).json()["access_token"]
    headers = _auth_headers(token)
    _publish(client, book_title="Shelf Book", chapter_title="First", content="hello")
    client.put("/api/bookshelf/1", headers=headers)
    client.post("/api/auth/trust-device", json={"fingerprint": "fp-admin", "device_info": "test"}, headers=headers)

    shelves = client.get("/api/admin/bookshelf/shelves", headers=headers)
    items = client.get("/api/admin/bookshelf/items", headers=headers)
    devices = client.get("/api/admin/devices", headers=headers)
    revoked = client.delete(f"/api/admin/devices/{devices.json()['items'][0]['id']}", headers=headers)
    audits = client.get("/api/admin/audit-logs", headers=headers)

    assert shelves.status_code == 200
    assert shelves.json()["items"][0]["book_count"] == 1
    assert items.status_code == 200
    assert items.json()["items"][0]["book_title"] == "Shelf Book"
    assert revoked.status_code == 200
    assert any(item["action"] == "revoke" and item["object_type"] == "trusted_device" for item in audits.json()["items"])


def test_web_base_url_is_validated(tmp_path: Path) -> None:
    client = _client(tmp_path, web_base_url="https://example.test/read")

    response = _publish(client)

    assert response.status_code == 200
    assert response.json()["web_url"].startswith("https://example.test/read/books/")


def test_web_base_url_rejects_unsafe_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_app(db_path=tmp_path / "bookstore.db", web_base_url="file:///etc/passwd")
    with pytest.raises(ValueError):
        create_app(db_path=tmp_path / "bookstore.db", web_base_url="https://user:pass@example.test")
