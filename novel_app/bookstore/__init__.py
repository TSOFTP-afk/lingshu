"""bookstore 子模块 — 重新导出公共 API 以保持向后兼容。"""

from .app import create_app
from .cloud_store import (
    CloudBookStore,
    _book_row,
    _bookshelf_row,
    _bookshelf_shelf_row,
    _chapter_list_row,
    _compact_summary,
    _normalize_book_tags,
    _validate_cloud_table,
)
from .models import (
    CLIENT_PASSWORD_ITERATIONS,
    CLIENT_PASSWORD_PEPPER,
    CLIENT_PASSWORD_SALT,
    DEFAULT_BOOKSHELF_NAME,
    DEFAULT_DB_PATH,
    DEFAULT_WEB_BASE_URL,
    LEGACY_DEFAULT_BOOK_LIBRARY_NAME,
    ROOT_DIR,
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    LoginPayload,
    PublishChapterPayload,
    RegisterPayload,
    TrustDevicePayload,
    _admin_usernames_from_env,
    _connect,
    _default_bookshelf_name,
    _ensure_cloud_tables,
    _ensure_column,
    _load_or_generate_secret,
    _normalize_web_base_url,
    _sql_identifier,
    _system_default_bookshelf_names,
    initialize_database,
)
from .security import (
    _bearer_token,
    _escape_like,
    _fulltext_content_hash,
    _generate_token,
    _hash_login_password,
    _hash_password,
    _looks_like_client_hash,
    _masked_token,
    _online_seconds_expr,
    _password_candidates,
    _public_user,
    _safe_int,
    _seconds_between_sql,
    _token_hash,
    _verify_login_password,
    _verify_password,
    client_password_hash,
    estimate_token_count,
)
from .store import BookstoreStore

__all__ = [
    # models
    "ROOT_DIR", "DEFAULT_DB_PATH", "DEFAULT_WEB_BASE_URL",
    "CLIENT_PASSWORD_PEPPER", "CLIENT_PASSWORD_SALT", "CLIENT_PASSWORD_ITERATIONS",
    "DEFAULT_BOOKSHELF_NAME", "LEGACY_DEFAULT_BOOK_LIBRARY_NAME",
    "_load_or_generate_secret", "_connect", "_sql_identifier", "_ensure_column",
    "_normalize_web_base_url", "_default_bookshelf_name",
    "_system_default_bookshelf_names", "_admin_usernames_from_env",
    "_ensure_cloud_tables", "initialize_database",
    "PublishChapterPayload", "LoginPayload", "RegisterPayload",
    "AuthorBookCreatePayload", "AuthorBookUpdatePayload",
    "AuthorChapterUpdatePayload", "BookshelfProgressPayload",
    "BookshelfCreatePayload", "AdminUserUpdatePayload",
    "AdminBookUpdatePayload", "AdminChapterUpdatePayload",
    "TrustDevicePayload",
    # security
    "_hash_password", "_verify_password", "client_password_hash",
    "_looks_like_client_hash", "_password_candidates",
    "_hash_login_password", "_verify_login_password",
    "_generate_token", "_token_hash",
    "_safe_int", "_seconds_between_sql", "_online_seconds_expr",
    "_masked_token", "_fulltext_content_hash", "estimate_token_count",
    "_escape_like", "_bearer_token", "_public_user",
    # store
    "BookstoreStore",
    # cloud store
    "CloudBookStore", "_validate_cloud_table",
    "_compact_summary", "_normalize_book_tags",
    "_book_row", "_chapter_list_row", "_bookshelf_row", "_bookshelf_shelf_row",
    # app
    "create_app",
]

app = create_app()
