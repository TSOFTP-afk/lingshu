from __future__ import annotations

import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "bookstore_demo.db"
DEFAULT_WEB_BASE_URL = "http://127.0.0.1:5173"
def _load_or_generate_secret(env_key: str, filename: str) -> bytes:
    """从环境变量加载密钥；若未设置则从数据目录的持久化文件读取或自动生成。"""
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val.encode("utf-8")

    # 尝试从数据目录读取已持久化的密钥
    _data_dir = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR") or os.environ.get("BOOKSTORE_DB_PATH")
    if _data_dir:
        secret_file = Path(_data_dir).parent if Path(_data_dir).suffix else Path(_data_dir)
        secret_file = secret_file / filename
    else:
        secret_file = DEFAULT_DB_PATH.parent / filename

    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").encode("utf-8")

    # 自动生成随机密钥并持久化
    generated = secrets.token_hex(32)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(generated, encoding="utf-8")
    except OSError:
        pass  # 无法持久化时仍可使用内存中的随机值
    return generated.encode("utf-8")


CLIENT_PASSWORD_PEPPER = _load_or_generate_secret("LINGSHU_PASSWORD_PEPPER", ".password_pepper")
CLIENT_PASSWORD_SALT = _load_or_generate_secret("LINGSHU_PASSWORD_SALT", ".password_salt")
CLIENT_PASSWORD_ITERATIONS = 100_000
DEFAULT_BOOKSHELF_NAME = "檀墨书箱"
LEGACY_DEFAULT_BOOK_LIBRARY_NAME = "我的书" + "库"


class PublishChapterPayload(BaseModel):
    source_app: str = Field(default="lingshu-desktop", min_length=1)
    source_book_id: int | str
    source_volume_id: int | str | None = None
    source_chapter_id: int | str
    book_title: str = Field(min_length=1)
    volume_title: str = ""
    chapter_title: str = Field(min_length=1)
    sort_order: int = 0
    outline: str = ""
    summary_text: str = ""
    content: str = Field(min_length=1)
    ai_probability: int = 0
    ai_probability_level: str = "none"
    updated_at: str = ""

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("章节正文不能为空")
        return value

    @field_validator("ai_probability")
    @classmethod
    def normalize_probability(cls, value: int) -> int:
        return max(0, min(100, int(value or 0)))


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class RegisterPayload(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=100)
    is_author: int = Field(default=1, ge=0, le=1)


class AuthorBookCreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(default="", max_length=4000)
    sub_tags: str = Field(default="", max_length=500)
    category: str = Field(default="本地上传", max_length=50)
    cover_url: str = Field(default="", max_length=2048)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("作品名称不能为空")
        return text


class AuthorBookUpdatePayload(BaseModel):
    summary: str = Field(default="", max_length=4000)


class AuthorChapterUpdatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    volume_title: str = Field(default="正文", max_length=100)
    content: str = Field(default="", max_length=1_000_000)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("章节名称不能为空")
        return text

    @field_validator("volume_title")
    @classmethod
    def normalize_volume_title(cls, value: str) -> str:
        return str(value or "").strip() or "正文"


class BookshelfProgressPayload(BaseModel):
    chapter_id: int = Field(gt=0)


class BookshelfCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("书架名称不能为空")
        return text


class AdminUserUpdatePayload(BaseModel):
    is_author: int | None = Field(default=None, ge=0, le=1)
    is_admin: int | None = Field(default=None, ge=0, le=1)
    status: str | None = Field(default=None, max_length=30)


class AdminBookUpdatePayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=50)
    sub_tags: str | None = Field(default=None, max_length=500)
    cover_url: str | None = Field(default=None, max_length=2048)
    is_test: int | None = Field(default=None, ge=0, le=1)


class AdminChapterUpdatePayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    volume_title: str | None = Field(default=None, max_length=100)
    outline: str | None = Field(default=None, max_length=4000)
    summary_text: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=1_000_000)
    sort_order: int | None = None
    status: str | None = Field(default=None, max_length=30)
    published_at: str | None = Field(default=None, max_length=40)
    ai_probability: int | None = Field(default=None, ge=0, le=100)
    ai_probability_level: str | None = Field(default=None, max_length=30)


class TrustDevicePayload(BaseModel):
    fingerprint: str = Field(min_length=1, max_length=128)
    device_info: str = Field(default="", max_length=4000)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _sql_identifier(value: str) -> str:
    text = str(value or "")
    if not text or text[0].isdigit() or not all(char.isalnum() or char == "_" for char in text):
        raise ValueError(f"Unsafe SQL identifier: {text!r}")
    return '"' + text.replace('"', '""') + '"'


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    try:
        sql = (
            "ALTER TABLE "
            + _sql_identifier(table_name)
            + " ADD COLUMN "
            + _sql_identifier(column_name)
            + " "
            + definition
        )
        connection.execute(sql)
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def _normalize_web_base_url(value: str) -> str:
    text = str(value or DEFAULT_WEB_BASE_URL).strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("BOOKSTORE_WEB_BASE_URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("BOOKSTORE_WEB_BASE_URL must not include credentials")
    return text


def _default_bookshelf_name() -> str:
    return DEFAULT_BOOKSHELF_NAME


def _system_default_bookshelf_names() -> set[str]:
    return {DEFAULT_BOOKSHELF_NAME, LEGACY_DEFAULT_BOOK_LIBRARY_NAME, "我的书架"}


def _admin_usernames_from_env() -> set[str]:
    raw = os.environ.get("BOOKSTORE_ADMIN_USERS", "")
    return {name.strip() for name in raw.split(",") if name.strip()}


def _ensure_cloud_tables(connection: sqlite3.Connection) -> None:
    """创建云端同步相关的所有表（幂等）。"""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS cloud_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            outline_text TEXT NOT NULL DEFAULT '',
            outline_data_json TEXT NOT NULL DEFAULT '',
            world_text TEXT NOT NULL DEFAULT '',
            world_data_json TEXT NOT NULL DEFAULT '',
            cover_image_path TEXT NOT NULL DEFAULT '',
            local_book_id INTEGER,
            source_type TEXT NOT NULL DEFAULT 'user_upload',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_volumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            outline_text TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            local_volume_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            cloud_volume_id INTEGER,
            title TEXT NOT NULL,
            outline TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            summary_text TEXT NOT NULL DEFAULT '',
            chapter_type TEXT NOT NULL DEFAULT '正文',
            sort_order INTEGER NOT NULL DEFAULT 0,
            ai_probability INTEGER NOT NULL DEFAULT 0,
            ai_probability_level TEXT NOT NULL DEFAULT 'none',
            local_chapter_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE,
            FOREIGN KEY (cloud_volume_id) REFERENCES cloud_volumes(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS cloud_characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            profile_text TEXT NOT NULL DEFAULT '',
            profile_data_json TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            graph_x REAL NOT NULL DEFAULT 0,
            graph_y REAL NOT NULL DEFAULT 0,
            local_character_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_character_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            source_character_id INTEGER NOT NULL,
            target_character_id INTEGER NOT NULL,
            relationship_type TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE,
            FOREIGN KEY (source_character_id) REFERENCES cloud_characters(id) ON DELETE CASCADE,
            FOREIGN KEY (target_character_id) REFERENCES cloud_characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_world_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '设定',
            content_text TEXT NOT NULL DEFAULT '',
            local_world_entry_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_analysis_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'book',
            status TEXT NOT NULL DEFAULT 'created',
            pipeline_version TEXT NOT NULL DEFAULT 'draft_mvp_v1',
            input_hash TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            error_text TEXT NOT NULL DEFAULT '',
            meta_json TEXT NOT NULL DEFAULT '{}',
            local_run_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_analysis_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            cloud_run_id INTEGER NOT NULL,
            card_uid TEXT NOT NULL,
            card_type TEXT NOT NULL,
            entity_uid TEXT NOT NULL DEFAULT '',
            card_version INTEGER NOT NULL DEFAULT 1,
            ars_score REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'draft',
            payload_json TEXT NOT NULL,
            diff_json TEXT NOT NULL DEFAULT '{}',
            applied_table TEXT NOT NULL DEFAULT '',
            applied_id INTEGER,
            applied_at DATETIME,
            local_card_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE,
            FOREIGN KEY (cloud_run_id) REFERENCES cloud_analysis_runs(id) ON DELETE CASCADE,
            UNIQUE(cloud_run_id, card_uid)
        );

        CREATE TABLE IF NOT EXISTS cloud_review_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            cloud_chapter_id INTEGER,
            scope_type TEXT NOT NULL DEFAULT 'chapter',
            status TEXT NOT NULL DEFAULT 'completed',
            truth_snapshot TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            overall_score INTEGER NOT NULL DEFAULT 0,
            local_run_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            applied_at DATETIME,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE,
            FOREIGN KEY (cloud_chapter_id) REFERENCES cloud_chapters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_review_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_run_id INTEGER NOT NULL,
            agent TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'low',
            category TEXT NOT NULL DEFAULT '',
            location_hint TEXT NOT NULL DEFAULT '',
            quote_text TEXT NOT NULL DEFAULT '',
            issue_text TEXT NOT NULL DEFAULT '',
            suggestion_text TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_run_id) REFERENCES cloud_review_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_chapter_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_book_id INTEGER NOT NULL,
            cloud_chapter_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE CASCADE,
            FOREIGN KEY (cloud_chapter_id) REFERENCES cloud_chapters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_chapter_tags (
            cloud_chapter_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (cloud_chapter_id, tag),
            FOREIGN KEY (cloud_chapter_id) REFERENCES cloud_chapters(id) ON DELETE CASCADE
        );

        -- 云端人物状态机三表（镜像本地 character_state_machines/cycles/snapshots）
        -- 用于范例小说分发与多用户状态机同步
        CREATE TABLE IF NOT EXISTS cloud_character_state_machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_character_id INTEGER NOT NULL UNIQUE,
            local_state_machine_id INTEGER,
            desire_text TEXT NOT NULL DEFAULT '',
            desire_origin TEXT NOT NULL DEFAULT '',
            desire_anchor TEXT NOT NULL DEFAULT '',
            desire_extreme TEXT NOT NULL DEFAULT '',
            desire_fear_mirror TEXT NOT NULL DEFAULT '',
            mbti_type TEXT NOT NULL DEFAULT '',
            mbti_i_e TEXT NOT NULL DEFAULT '',
            mbti_n_s TEXT NOT NULL DEFAULT '',
            mbti_t_f TEXT NOT NULL DEFAULT '',
            mbti_j_p TEXT NOT NULL DEFAULT '',
            mbti_strategy TEXT NOT NULL DEFAULT '',
            mbti_advantage TEXT NOT NULL DEFAULT '',
            mbti_blindspot TEXT NOT NULL DEFAULT '',
            fate_type TEXT NOT NULL DEFAULT '',
            fate_content TEXT NOT NULL DEFAULT '',
            fate_trigger TEXT NOT NULL DEFAULT '',
            fate_target TEXT NOT NULL DEFAULT '',
            fate_limit TEXT NOT NULL DEFAULT '',
            belief_core TEXT NOT NULL DEFAULT '',
            belief_origin TEXT NOT NULL DEFAULT '',
            belief_alignment TEXT NOT NULL DEFAULT '',
            belief_sacrifice TEXT NOT NULL DEFAULT '',
            belief_taboo TEXT NOT NULL DEFAULT '',
            current_desire_state TEXT NOT NULL DEFAULT 'original',
            current_mbti_state TEXT NOT NULL DEFAULT '',
            current_fate_state TEXT NOT NULL DEFAULT 'dormant',
            current_belief_state TEXT NOT NULL DEFAULT 'stable',
            current_friction TEXT NOT NULL DEFAULT 'none',
            current_dilemma TEXT NOT NULL DEFAULT '',
            total_change_score INTEGER NOT NULL DEFAULT 0,
            last_update_source TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_character_id) REFERENCES cloud_characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_character_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_character_id INTEGER NOT NULL,
            cycle_type TEXT NOT NULL,
            cycle_code TEXT NOT NULL DEFAULT '',
            triggered_desire TEXT NOT NULL DEFAULT '',
            belief_filtered_strategy TEXT NOT NULL DEFAULT '',
            action_taken TEXT NOT NULL DEFAULT '',
            world_feedback TEXT NOT NULL DEFAULT '',
            feedback_intensity TEXT NOT NULL DEFAULT '',
            mbti_change TEXT NOT NULL DEFAULT '',
            star_state TEXT NOT NULL DEFAULT '',
            fate_state TEXT NOT NULL DEFAULT '',
            internal_friction TEXT NOT NULL DEFAULT '',
            change_score INTEGER NOT NULL DEFAULT 0,
            cumulative_score INTEGER NOT NULL DEFAULT 0,
            batch_span TEXT NOT NULL DEFAULT '',
            batch_micro_count INTEGER NOT NULL DEFAULT 0,
            batch_summary TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            local_cycle_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_character_id) REFERENCES cloud_characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS cloud_character_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cloud_character_id INTEGER NOT NULL,
            snapshot_no INTEGER NOT NULL DEFAULT 1,
            trigger_type TEXT NOT NULL DEFAULT 'threshold',
            trigger_detail TEXT NOT NULL DEFAULT '',
            related_cycle_id INTEGER,
            desire_state TEXT NOT NULL DEFAULT '',
            mbti_state TEXT NOT NULL DEFAULT '',
            fate_state TEXT NOT NULL DEFAULT '',
            belief_state TEXT NOT NULL DEFAULT '',
            friction_level TEXT NOT NULL DEFAULT '',
            phase_dilemma TEXT NOT NULL DEFAULT '',
            phase_change_summary TEXT NOT NULL DEFAULT '',
            micro_cycle_summary TEXT NOT NULL DEFAULT '',
            total_score_at_snapshot INTEGER NOT NULL DEFAULT 0,
            local_snapshot_id INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cloud_character_id) REFERENCES cloud_characters(id) ON DELETE CASCADE,
            UNIQUE(cloud_character_id, snapshot_no)
        );

        CREATE INDEX IF NOT EXISTS idx_cloud_state_machines_character
        ON cloud_character_state_machines(cloud_character_id);
        CREATE INDEX IF NOT EXISTS idx_cloud_cycles_character
        ON cloud_character_cycles(cloud_character_id, sort_order);
        CREATE INDEX IF NOT EXISTS idx_cloud_snapshots_character
        ON cloud_character_snapshots(cloud_character_id, snapshot_no);

        CREATE INDEX IF NOT EXISTS idx_cloud_books_user
        ON cloud_books(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cloud_volumes_book
        ON cloud_volumes(cloud_book_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_cloud_chapters_book
        ON cloud_chapters(cloud_book_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_cloud_chapters_volume
        ON cloud_chapters(cloud_book_id, cloud_volume_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_cloud_characters_book
        ON cloud_characters(cloud_book_id);
        CREATE INDEX IF NOT EXISTS idx_cloud_relationships_book
        ON cloud_character_relationships(cloud_book_id);
        CREATE INDEX IF NOT EXISTS idx_cloud_world_entries_book
        ON cloud_world_entries(cloud_book_id);
        CREATE INDEX IF NOT EXISTS idx_cloud_analysis_runs_book
        ON cloud_analysis_runs(cloud_book_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_cloud_analysis_cards_run
        ON cloud_analysis_cards(cloud_run_id, card_type, status);
        CREATE INDEX IF NOT EXISTS idx_cloud_review_runs_book
        ON cloud_review_runs(cloud_book_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_cloud_review_findings_run
        ON cloud_review_findings(cloud_run_id);
        CREATE INDEX IF NOT EXISTS idx_cloud_chapter_events_book
        ON cloud_chapter_events(cloud_book_id, sort_order, id);
        CREATE INDEX IF NOT EXISTS idx_cloud_chapter_events_chapter
        ON cloud_chapter_events(cloud_chapter_id, sort_order, id);

        CREATE TABLE IF NOT EXISTS cloud_book_metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            local_book_id INTEGER NOT NULL,
            cloud_book_id INTEGER,
            title TEXT NOT NULL,
            chapter_count INTEGER NOT NULL DEFAULT 0,
            word_count INTEGER NOT NULL DEFAULT 0,
            character_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (cloud_book_id) REFERENCES cloud_books(id) ON DELETE SET NULL,
            UNIQUE(user_id, local_book_id)
        );

        CREATE INDEX IF NOT EXISTS idx_cloud_book_metas_user
        ON cloud_book_metas(user_id, updated_at DESC);
        """
    )
    _ensure_column(connection, "cloud_books", "cover_image_path", "TEXT NOT NULL DEFAULT ''")
    # 范例小说分发依赖 source_type 区分 'sample' / 'sample_clone' / 'user_upload'
    _ensure_column(connection, "cloud_books", "source_type", "TEXT NOT NULL DEFAULT 'user_upload'")

    # 用户级 AI 设置（按 user_id 隔离，替代全局 ai_settings.json）
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_ai_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            purpose TEXT NOT NULL,
            profile_json TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, purpose),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_user_ai_settings_user ON user_ai_settings(user_id);
        """
    )


def initialize_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    # 延迟导入，避免 models ↔ security 循环依赖
    from .security import _token_hash

    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_app TEXT NOT NULL,
                source_book_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '本地上传',
                sub_tags TEXT NOT NULL DEFAULT '',
                cover_url TEXT NOT NULL DEFAULT '',
                is_test INTEGER NOT NULL DEFAULT 0,
                deleted_at DATETIME,
                deleted_by INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_app, source_book_id)
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_chapter_id TEXT NOT NULL,
                source_volume_id TEXT NOT NULL DEFAULT '',
                volume_title TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                outline TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                ai_probability INTEGER NOT NULL DEFAULT 0,
                ai_probability_level TEXT NOT NULL DEFAULT 'none',
                status TEXT NOT NULL DEFAULT 'published',
                source_updated_at TEXT NOT NULL DEFAULT '',
                published_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at DATETIME,
                deleted_by INTEGER,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                UNIQUE(book_id, source_chapter_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bookstore_chapters_book_order
            ON chapters(book_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_bookstore_books_updated
            ON books(updated_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_author INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                bind_reader_id INTEGER,
                disabled_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL DEFAULT '',
                user_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at DATETIME,
                expires_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS trusted_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                device_info TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                trusted_until DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, fingerprint)
            );

            CREATE INDEX IF NOT EXISTS idx_bookstore_trusted_devices_user
            ON trusted_devices(user_id, trusted_until DESC);

            CREATE TABLE IF NOT EXISTS bookshelf_shelves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                deleted_at DATETIME,
                deleted_by INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, name)
            );

            CREATE INDEX IF NOT EXISTS idx_bookstore_shelves_user
            ON bookshelf_shelves(user_id, is_default DESC, updated_at DESC);

            CREATE TABLE IF NOT EXISTS bookshelf_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                shelf_id INTEGER,
                book_id INTEGER NOT NULL,
                last_chapter_id INTEGER,
                deleted_at DATETIME,
                deleted_by INTEGER,
                added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (shelf_id) REFERENCES bookshelf_shelves(id) ON DELETE SET NULL,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (last_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                UNIQUE(user_id, book_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bookstore_shelf_user_updated
            ON bookshelf_items(user_id, updated_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'operator',
                status TEXT NOT NULL DEFAULT 'active',
                last_login_at TEXT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS admin_auth_tokens (
                token TEXT PRIMARY KEY,
                admin_user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_user_id) REFERENCES admin_users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created
            ON admin_audit_logs(created_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS book_fulltexts (
                book_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                chapter_count INTEGER NOT NULL DEFAULT 0,
                char_count INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_book_fulltexts_user_updated
            ON book_fulltexts(user_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS user_online_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                login_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                logout_at DATETIME,
                estimated_online_seconds INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_online_sessions_user
            ON user_online_sessions(user_id, login_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_online_sessions_token_hash
            ON user_online_sessions(token_hash);

            CREATE TABLE IF NOT EXISTS user_analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                book_id INTEGER,
                run_ref TEXT NOT NULL DEFAULT '',
                analysis_mode TEXT NOT NULL DEFAULT '',
                input_chars INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                source TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_user_analysis_runs_user_created
            ON user_analysis_runs(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_analysis_runs_book
            ON user_analysis_runs(book_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_ai_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                book_id INTEGER,
                analysis_run_id INTEGER,
                feature TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                token_source TEXT NOT NULL DEFAULT 'unknown',
                input_chars INTEGER NOT NULL DEFAULT 0,
                output_chars INTEGER NOT NULL DEFAULT 0,
                trace_id TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT '',
                latency_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                error_text TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE SET NULL,
                FOREIGN KEY (analysis_run_id) REFERENCES user_analysis_runs(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_user_ai_usage_events_user_created
            ON user_ai_usage_events(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_ai_usage_events_book_created
            ON user_ai_usage_events(book_id, created_at DESC);
            """
        )
        _ensure_column(connection, "auth_tokens", "created_at", "DATETIME")
        _ensure_column(connection, "auth_tokens", "revoked_at", "DATETIME")
        _ensure_column(connection, "auth_tokens", "token_hash", "TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookstore_auth_tokens_hash ON auth_tokens(token_hash)"
        )
        _ensure_column(connection, "books", "sub_tags", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "books", "deleted_at", "DATETIME")
        _ensure_column(connection, "books", "deleted_by", "INTEGER")
        _ensure_column(connection, "chapters", "status", "TEXT NOT NULL DEFAULT 'published'")
        _ensure_column(connection, "chapters", "deleted_at", "DATETIME")
        _ensure_column(connection, "chapters", "deleted_by", "INTEGER")
        _ensure_column(connection, "users", "is_admin", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "users", "status", "TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(connection, "users", "disabled_at", "DATETIME")
        _ensure_column(connection, "users", "updated_at", "DATETIME")
        _ensure_column(connection, "bookshelf_shelves", "deleted_at", "DATETIME")
        _ensure_column(connection, "bookshelf_shelves", "deleted_by", "INTEGER")
        _ensure_column(connection, "bookshelf_items", "shelf_id", "INTEGER")
        _ensure_column(connection, "user_ai_usage_events", "trace_id", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "user_ai_usage_events", "prompt_version", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "user_ai_usage_events", "schema_version", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(connection, "user_ai_usage_events", "latency_ms", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "bookshelf_items", "deleted_at", "DATETIME")
        _ensure_column(connection, "bookshelf_items", "deleted_by", "INTEGER")
        connection.execute("UPDATE auth_tokens SET created_at = COALESCE(created_at, datetime(expires_at, '-7 days'))")
        for row in connection.execute("SELECT token FROM auth_tokens WHERE token_hash IS NULL OR token_hash = ''").fetchall():
            connection.execute("UPDATE auth_tokens SET token_hash = ? WHERE token = ?", (_token_hash(row["token"]), row["token"]))
        connection.execute("UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)")
        connection.execute(
            """
            UPDATE chapters
            SET status = 'draft', published_at = ''
            WHERE status = 'published'
              AND source_chapter_id LIKE 'web-%'
              AND TRIM(content) = ''
            """
        )
        _ensure_cloud_tables(connection)
        connection.commit()
