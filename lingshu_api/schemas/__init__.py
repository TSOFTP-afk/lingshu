"""lingshu_api schemas — Pydantic 模型汇总。"""
from lingshu_api.schemas.admin_auth import (
    AdminInfoResponse,
    AdminLoginPayload,
    AdminLoginResponse,
)
from lingshu_api.schemas.auth import (
    LoginResponse,
    UserInfoResponse,
)
from lingshu_api.schemas.auth import (
    OkResponse as AuthOkResponse,
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
    "AdminInfoResponse",
    "AdminLoginPayload",
    "AdminLoginResponse",
    "AuthOkResponse",
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
    "LoginResponse",
    "SnapshotListResponse",
    "UserInfoResponse",
    "WorkspaceOkResponse",
    "WorkspaceSettingsPayload",
    "WorkspaceSettingsResponse",
]
