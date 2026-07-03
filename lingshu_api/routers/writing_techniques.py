"""网文写作技巧集 API 路由。

提供索引查询、详情、搜索、按写作阶段推荐，以及适配长篇生成的 selected_skills 转换。
供前端在长篇生成前选择写作技巧，所选 skill 可注入 generation 流程。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from lingshu_api.dependencies import require_login
from novel_app.writing_techniques.indexer import TechniqueIndexer

router = APIRouter(prefix="/api/workspace/writing-techniques", tags=["writing-techniques"])


def _indexer() -> TechniqueIndexer:
    return TechniqueIndexer()


@router.get("/index")
def get_index(user: dict = Depends(require_login)) -> dict:
    """获取写作技巧集完整索引（技能 + 参考 + 阶段映射）。"""
    return _indexer().full_index()


@router.get("/skills")
def list_skills(user: dict = Depends(require_login)) -> dict:
    """列出全部可执行技能（轻量索引）。"""
    return {"items": _indexer().skill_index()}


@router.get("/skills/{skill_id}")
def get_skill_detail(skill_id: str, user: dict = Depends(require_login)) -> dict:
    """获取单个技能的完整内容。"""
    detail = _indexer().skill_detail(skill_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"技能 {skill_id} 不存在")
    return detail


@router.get("/references")
def list_references(user: dict = Depends(require_login)) -> dict:
    """列出全部参考知识库文档（轻量索引）。"""
    return {"items": _indexer().reference_index()}


@router.get("/references/{ref_id}")
def get_reference_detail(ref_id: str, user: dict = Depends(require_login)) -> dict:
    """获取单篇参考文档的完整内容。"""
    detail = _indexer().reference_detail(ref_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"参考文档 {ref_id} 不存在")
    return detail


@router.get("/search")
def search_skills(
    stage: str | None = Query(None, description="写作阶段：新书立项/单章写作/爽点设计/中期维护/改稿去味/发布变现"),
    category: str | None = Query(None, description="类别，如 开篇/爽点/节奏/对话"),
    q: str | None = Query(None, description="关键词，匹配名称/描述/触发场景/正文"),
    user: dict = Depends(require_login),
) -> dict:
    """按写作阶段/类别/关键词检索技能。"""
    return {"items": _indexer().search(stage=stage, category=category, keyword=q)}


@router.get("/recommend")
def recommend_by_stage(
    stage: str = Query(..., description="写作阶段：新书立项/单章写作/爽点设计/中期维护/改稿去味/发布变现"),
    user: dict = Depends(require_login),
) -> dict:
    """按写作阶段推荐技能组合。"""
    return {"stage": stage, "items": _indexer().recommend(stage)}


@router.post("/to-selected-skills")
def convert_to_selected_skills(
    payload: dict,
    user: dict = Depends(require_login),
) -> dict:
    """把选中的写作技巧 skill_id 列表转换为长篇生成 selected_skills 格式。

    请求体: {"skill_ids": ["SKILL-001", "SKILL-012"]}
    返回: {"items": [{"name":..., "category":..., "instruction_text":...}, ...]}

    前端在发起长篇生成前调用此端点，把返回的 items 直接作为
    multi_agent_generate_from_outline / stream_generate 的 selected_skills 参数传入。
    """
    skill_ids = payload.get("skill_ids") or []
    if not isinstance(skill_ids, list):
        raise HTTPException(status_code=400, detail="skill_ids 必须是列表")
    items = _indexer().to_selected_skills(skill_ids)
    return {"items": items, "count": len(items)}
