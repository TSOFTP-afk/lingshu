"""bookstore 仓储层 — BookstoreStore 按域拆出的数据访问类（行为不变）。"""

from .admin_repository import AdminRepository
from .auth_repository import AuthRepository
from .book_repository import BookRepository
from .common import (
    SAMPLE_NOVEL_USERNAME,
    _book_user_id,
    _rebuild_book_fulltext,
    _validate_column,
    _validate_columns,
    _validate_table,
)
from .device_repository import DeviceRepository
from .shelf_repository import ShelfRepository
from .stats_repository import StatsRepository

__all__ = [
    "AdminRepository",
    "AuthRepository",
    "BookRepository",
    "DeviceRepository",
    "ShelfRepository",
    "StatsRepository",
    "SAMPLE_NOVEL_USERNAME",
    "_book_user_id",
    "_rebuild_book_fulltext",
    "_validate_column",
    "_validate_columns",
    "_validate_table",
]
