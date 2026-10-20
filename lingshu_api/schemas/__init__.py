"""lingshu_api schemas — Pydantic 模型汇总。"""
from lingshu_api.schemas.auth import (
    UserInfoResponse,
)
from lingshu_api.schemas.settings import (
    AIProfilePayload,
    AISettingsPayload,
    AISettingsResponse,
    AITestRequest,
    AITestResponse,
    WorkspaceSettingsPayload,
    WorkspaceSettingsResponse,
)
from lingshu_api.schemas.workspace import (
    BookItemResponse,
    BookListResponse,
    ChapterItemResponse,
    ChapterListResponse,
    SnapshotListResponse,
    VolumeItemResponse,
)
from lingshu_api.schemas.workspace import (
    OkResponse as WorkspaceOkResponse,
)

__all__ = [
    "AIProfilePayload",
    "AISettingsPayload",
    "AISettingsResponse",
    "AITestRequest",
    "AITestResponse",
    "BookItemResponse",
    "BookListResponse",
    "ChapterItemResponse",
    "ChapterListResponse",
    "VolumeItemResponse",
    "SnapshotListResponse",
    "UserInfoResponse",
    "WorkspaceOkResponse",
    "WorkspaceSettingsPayload",
    "WorkspaceSettingsResponse",
]
