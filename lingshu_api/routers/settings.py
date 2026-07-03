from __future__ import annotations

from fastapi import APIRouter, Depends

from lingshu_api.dependencies import require_ai_access, require_login
from lingshu_api.schemas.settings import (
    AISettingsPayload,
    AISettingsResponse,
    AITestRequest,
    AITestResponse,
    WorkspaceSettingsPayload,
    WorkspaceSettingsResponse,
)
from lingshu_api.services.ai_settings import (
    AI_PURPOSES,
    load_ai_settings,
    resolve_ai_profile,
    save_ai_settings,
    validate_profile_ready,
)
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from lingshu_api.services.workspace_settings import (
    load_workspace_settings,
    save_workspace_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _mask_api_key(key: str) -> str:
    if not key or len(key) <= 4:
        return "***" if key else ""
    return "***" + key[-4:]


@router.get("/ai", response_model=AISettingsResponse)
def get_ai_settings(
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    settings = load_ai_settings(db.db.data_dir, reveal_secrets=False, user_id=int(user["id"]))
    result = {"ok": True, "purposes": AI_PURPOSES, **settings}
    for profile in result.get("profiles", {}).values():
        if isinstance(profile, dict) and "api_key_configured" in profile:
            # 如果有已配置的密钥，返回掩码占位符（不返回空字符串导致前端显示空白）
            profile["api_key"] = "***" if profile["api_key_configured"] else ""
    return result


@router.put("/ai", response_model=AISettingsResponse)
def put_ai_settings(payload: AISettingsPayload, user: dict = Depends(require_ai_access), db: WorkspaceDB = Depends(get_workspace_db)):
    # 过滤掉掩码密钥占位符，防止前端无意中将 "***" 覆盖真实密钥
    payload_dict = payload.model_dump()
    profiles = payload_dict.get("profiles")
    if isinstance(profiles, dict):
        for p in profiles.values():
            if isinstance(p, dict) and str(p.get("api_key") or "").startswith("***"):
                p.pop("api_key")
    settings = save_ai_settings(db.db.data_dir, payload_dict, user_id=int(user["id"]))
    result = {"ok": True, "purposes": AI_PURPOSES, **settings}
    for profile in result.get("profiles", {}).values():
        if isinstance(profile, dict) and "api_key" in profile:
            profile["api_key"] = _mask_api_key(str(profile["api_key"]))
    return result


@router.post("/ai/test", response_model=AITestResponse)
def test_ai_settings(payload: AITestRequest, user: dict = Depends(require_ai_access), db: WorkspaceDB = Depends(get_workspace_db)):
    purpose = payload.purpose
    profile_payload = payload.profile
    if profile_payload is not None:
        profile = profile_payload.model_dump()
    else:
        profile = resolve_ai_profile(db.db.data_dir, purpose, user_id=int(user["id"]))
    ok, message = validate_profile_ready(profile)
    return {"ok": ok, "message": message}


@router.get("/workspace", response_model=WorkspaceSettingsResponse)
def get_workspace_settings(user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    return {"ok": True, **load_workspace_settings(db.db.data_dir)}


@router.put("/workspace", response_model=WorkspaceSettingsResponse)
def put_workspace_settings(payload: WorkspaceSettingsPayload, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    return {"ok": True, **save_workspace_settings(db.db.data_dir, payload.model_dump())}
