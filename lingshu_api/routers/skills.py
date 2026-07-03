"""
Skills 管理 API — 对应 Qt drawer/skills.py
"""
from fastapi import APIRouter, Depends

from lingshu_api.dependencies import require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(prefix="/api/workspace", tags=["skills"])


@router.get("/books/{book_id}/skills")
def get_book_skills(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取作品关联的 Skills（全局/书籍级）。"""
    if not db.get_book(book_id):
        return {"items": []}
    global_skills = [dict(r) for r in db.db.list_bound_skills_for_global()]
    book_skills = [dict(r) for r in db.db.list_bound_skills_for_book(book_id)]
    return {"items": global_skills + book_skills, "global": global_skills, "book": book_skills}


@router.get("/skills")
def list_all_skills(user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出全部可用的 Skills。"""
    skills = [dict(r) for r in db.db.list_skills()]
    return {"items": skills}
