"""
工作台文件导入 API (TXT / MD / DOCX / EPUB)（原 lingshu_api/routers/workspace.py 拆分而来）。
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from lingshu_api.dependencies import check_book_owner, require_ai_access, try_cloud_sync
from lingshu_api.routers.workspace_common import logger
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.ai.service import SimpleAIService
from novel_app.text_importer import (
    ParsedBook,
    ParsedChapter,
    build_catalog_summary,
    merge_reparsed_chapters,
    parse_long_text,
)

router = APIRouter(tags=["workspace"])


# ================================================================
#  文件导入 (TXT / MD / DOCX)
# ================================================================

@router.post("/books/{book_id}/import-file", response_model=dict[str, Any])  # TODO: 细化为 ImportFileResponse
async def import_file_to_book(
    request: Request,
    book_id: int,
    file: UploadFile = File(...),
    skip_volumes: bool = Query(default=False),
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导入文件到现有作品（新增为卷/章）。"""
    def _check():
        check_book_owner(db, book_id, user)
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
    await asyncio.to_thread(_check)
    return await _handle_file_import(
        request,
        file,
        db,
        target_book_id=book_id,
        skip_volumes=skip_volumes,
        user_id=int(user["id"]),
        user=user,
    )


@router.post("/import-file", response_model=dict[str, Any])  # TODO: 细化为 ImportFileResponse
async def import_file_as_new_book(
    request: Request,
    title: str = Query(default="", description="新作品标题（可选，默认使用文件名）"),
    file: UploadFile = File(...),
    skip_volumes: bool = Query(default=False),
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导入文件创建为新作品。"""
    return await _handle_file_import(
        request,
        file,
        db,
        target_book_id=None,
        default_title=title,
        skip_volumes=skip_volumes,
        user_id=int(user["id"]),
        user=user,
    )


async def _handle_file_import(
    request: Request,
    file: UploadFile,
    db: WorkspaceDB,
    target_book_id: int | None = None,
    default_title: str = "",
    skip_volumes: bool = False,
    user_id: int | None = None,
    user: dict | None = None,
) -> dict[str, Any]:
    """处理文件导入的通用逻辑。"""
    raw_bytes = await file.read()

    if len(raw_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 50MB，请先拆分后再导入")

    suffix = Path(file.filename or "import.txt").suffix.lower()

    # 文件扩展名白名单校验
    _ALLOWED_IMPORT_EXTENSIONS = {".txt", ".md", ".docx", ".epub"}
    if suffix not in _ALLOWED_IMPORT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix}，仅允许 {', '.join(sorted(_ALLOWED_IMPORT_EXTENSIONS))}")

    # 解码文本
    try:
        if suffix == ".docx":
            import io

            from docx import Document
            doc = Document(io.BytesIO(raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            text = _decode_text(raw_bytes)
    except Exception as exc:
        logger.exception("无法读取文件")
        raise HTTPException(status_code=400, detail="无法读取文件") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 书名
    title = default_title or Path(file.filename or "导入作品").stem.strip()
    if not title:
        title = "导入作品"

    # 拆分章节：统一使用 AI 辅助分段检测
    try:
        parsed = await _parse_large_text_with_ai_splits(title, text, db, skip_volumes=skip_volumes, user_id=int(user["id"]))
    except Exception as exc:
        logger.exception("文本拆分失败")
        raise HTTPException(status_code=400, detail="文本拆分失败，请检查文件格式") from exc

    if not parsed.chapters:
        raise HTTPException(status_code=400, detail="没有识别到可导入的章节")

    # 如果用户关闭分卷 或 第一个章节没有分卷标记，则强制清空所有 volume_title 归入未分卷
    if skip_volumes or not parsed.chapters[0].volume_title:
        parsed = dataclasses.replace(
            parsed,
            chapters=[dataclasses.replace(c, volume_title=None) for c in parsed.chapters],
        )

    # 导入
    try:
        if target_book_id:
            result = await asyncio.to_thread(_append_parsed_to_book, db, target_book_id, parsed)
        else:
            result = await asyncio.to_thread(_create_book_from_parsed, db, parsed, user_id)
    except Exception as exc:
        logger.exception("写入失败")
        raise HTTPException(status_code=500, detail="写入失败，请稍后重试") from exc

    book_id = int(result["book_id"])

    def _after_import():
        try_cloud_sync(request, book_id, user)
        return db.get_book(book_id)

    item = await asyncio.to_thread(_after_import)
    volume_count = len({c.volume_title for c in parsed.chapters if c.volume_title})
    return {
        "ok": True,
        **result,
        "item": item,
        "stats": {
            "volume_count": volume_count,
            "chapter_count": len(parsed.chapters),
            "total_chars": sum(len(c.content.strip()) for c in parsed.chapters),
        },
    }


# 单次局部重检区域的最大字符数（防止给 AI 过大的文本块）
LOCAL_REPARSE_MAX_CHARS = 200_000
# 局部重检时在可疑区域两侧扩展的字符数（提供上下文给 AI）
LOCAL_REPARSE_CONTEXT_CHARS = 2000


async def _parse_large_text_with_ai_splits(
    title: str,
    text: str,
    db: WorkspaceDB,
    skip_volumes: bool = False,
    *,
    user_id: int | None = None,
) -> ParsedBook:
    """三阶段智能导入：正则解析 → AI 目录校验 → 问题区域局部重检。

    无论文件大小都优先使用正则解析（快速），然后让 AI 校验目录摘要。
    AI 不可用或校验通过时直接返回正则结果；发现可疑区域时局部重检。
    """
    # 关闭分卷时直接正则分段解析
    if skip_volumes:
        return await asyncio.to_thread(_fallback_chunk_parse, title, text)

    # === 阶段 1：正则快速解析 ===
    parsed = await asyncio.to_thread(_fallback_chunk_parse, title, text)
    if not parsed.chapters:
        return parsed

    # === 阶段 2：AI 目录校验 ===
    try:
        from lingshu_api.services.ai_settings import resolve_ai_profile
        profile = resolve_ai_profile(db.db.data_dir, "import", user_id=user_id)
        ai_service = SimpleAIService(
            api_key=profile.get("api_key") or None,
            base_url=profile.get("base_url") or None,
            model=profile.get("model") or None,
        )
        # 如果 AI 未配置，跳过校验直接返回正则结果
        if not ai_service.is_remote_configured():
            logger.warning("[三阶段导入] AI 未配置，跳过目录校验，使用正则结果: %s", title)
            return parsed
    except Exception as exc:
        logger.warning("[三阶段导入] AI 服务初始化失败，使用正则结果: %s", exc)
        return parsed

    try:
        catalog_summary = build_catalog_summary(parsed.chapters)
        logger.warning("[三阶段导入] 阶段1完成: 正则解析 %d 章, 目录摘要 %d 字符, 开始AI校验: %s",
                       len(parsed.chapters), len(catalog_summary), title)
        issues = await asyncio.to_thread(
            ai_service.review_import_catalog,
            catalog_summary,
            len(parsed.chapters),
        )
        logger.warning("[三阶段导入] 阶段2完成: AI校验返回 %d 个可疑区域: %s", len(issues), title)
        for i, issue in enumerate(issues):
            logger.warning("[三阶段导入]   可疑区域%d: 行%d-%d 原因: %s",
                           i+1, issue["start_line"], issue["end_line"], issue.get("reason", ""))
    except Exception as exc:
        logger.warning("[三阶段导入] AI 目录校验失败，使用正则结果: %s", exc)
        return parsed

    if not issues:
        logger.warning("[三阶段导入] AI 目录校验通过，共 %d 章: %s", len(parsed.chapters), title)
        return parsed

    # === 阶段 3：对每个可疑章节区间局部重检 ===
    merged_chapters = parsed.chapters
    for issue in issues:
        try:
            reparsed = await asyncio.to_thread(
                _reparse_chapters_with_ai,
                ai_service, merged_chapters, issue,
            )
            if reparsed:
                sc = issue["start_chapter"]
                ec = issue["end_chapter"]
                merged_chapters = merge_reparsed_chapters(
                    merged_chapters, reparsed, sc, ec,
                )
                logger.warning("[三阶段导入] 阶段3: 章节%d-%d 重检完成，得到 %d 章（原因: %s）",
                               sc, ec, len(reparsed), issue.get("reason", ""))
            else:
                logger.warning("[三阶段导入] 阶段3: 章节%d-%d 重检无结果，保留正则结果",
                               issue["start_chapter"], issue["end_chapter"])
        except Exception as exc:
            logger.warning("[三阶段导入] 阶段3: 章节%d-%d 重检失败，保留正则结果: %s",
                           issue["start_chapter"], issue["end_chapter"], exc)

    from novel_app.text_importer import _extract_book_outline
    return ParsedBook(
        title=parsed.title,
        outline=_extract_book_outline(title, merged_chapters),
        chapters=merged_chapters,
    )


def _reparse_chapters_with_ai(
    ai_service: "SimpleAIService",
    chapters: list[ParsedChapter],
    issue: dict[str, int],
) -> list[ParsedChapter]:
    """对可疑章节区间调用 AI 重新检测章节结构并解析。

    :param ai_service: 已配置的 AI 服务
    :param chapters: 当前完整的章节列表
    :param issue: ``{"start_chapter": int, "end_chapter": int, "reason": str}``
    :return: AI 重检后解析出的章节列表
    """
    sc = max(1, int(issue.get("start_chapter", 1)))
    ec = int(issue.get("end_chapter", sc))

    # 扩展上下文：取可疑区间前后各 1 章的内容
    ctx_start = max(1, sc - 1)
    ctx_end = min(len(chapters), ec + 1)

    # 拼接可疑区间（含上下文）的章节内容，用章节标题作为分隔标记
    parts: list[str] = []
    for idx in range(ctx_start, ctx_end + 1):
        chapter = chapters[idx - 1]
        # 用标题行标记章节边界，让 AI 能看到原始的切分方式
        parts.append(f"{chapter.title}\n{chapter.content}")
    region_text = "\n\n".join(parts)

    # 限制总长度，防止过大
    if len(region_text) > LOCAL_REPARSE_MAX_CHARS:
        region_text = region_text[:LOCAL_REPARSE_MAX_CHARS]

    if not region_text.strip():
        return []

    # 调用 AI 检测该区域的章节结构
    structure = ai_service.detect_chapter_structure(region_text)
    if not structure:
        return []

    # 用 AI 检测的结构解析区域文本
    region_parsed = parse_long_text("区域重检", region_text, structure)
    # 过滤掉上下文章节（只保留落在可疑区间内的章节）
    # 简单策略：如果重检后的章节数与原来不同，说明 AI 发现了问题，使用全部重检结果
    # （上下文的 1 章可能被合并/拆分，这是可接受的）
    return region_parsed.chapters


def _fallback_chunk_parse(title: str, text: str) -> ParsedBook:
    """正则解析（AI 不可用或关闭分卷时的回退方案）。

    直接一次性解析整个文本，保证章节行号相对于完整原文。
    正则解析即使 5MB 文本也是秒级完成，无需分段。
    """
    return parse_long_text(title, text)


def _decode_text(data: bytes) -> str:
    """智能解码文本文件（UTF-8 / UTF-16 / GBK）。"""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.count(b"\x00") > max(8, len(data) // 100):
        raise ValueError("文件看起来不是纯文本")
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("无法识别文本编码")


def _create_book_from_parsed(db: WorkspaceDB, parsed, user_id: int | None = None) -> dict:
    """从 ParsedBook 创建新书。"""
    book_id = db.db.create_book(parsed.title, user_id=user_id)

    # 保存自动生成的书籍大纲
    if parsed.outline:
        db.db.update_book_outline(book_id, parsed.outline)

    # 如果第一个章节就没有分卷，全部归入未分卷（无需检查后续）
    has_unassigned = not parsed.chapters[0].volume_title if parsed.chapters else True
    if has_unassigned:
        first_chapter_id = None
        for chapter in parsed.chapters:
            cid = db.db.create_chapter(book_id, chapter.title, None)
            db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
            if first_chapter_id is None:
                first_chapter_id = cid
        return {"book_id": book_id, "first_chapter_id": first_chapter_id}

    volume_ids: dict[str, int] = {}
    first_chapter_id = None

    for chapter in parsed.chapters:
        vid = None
        if chapter.volume_title:
            vid = volume_ids.get(chapter.volume_title)
            if vid is None:
                vid = db.db.create_volume(book_id, chapter.volume_title)
                volume_ids[chapter.volume_title] = vid

        cid = db.db.create_chapter(book_id, chapter.title, vid)
        db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
        if first_chapter_id is None:
            first_chapter_id = cid

    return {"book_id": book_id, "first_chapter_id": first_chapter_id}


def _append_parsed_to_book(db: WorkspaceDB, book_id: int, parsed) -> dict:
    """追加导入内容到已有书籍。"""
    # 追加导入的章节大纲
    if parsed.outline:
        db.db.update_book_outline(book_id, parsed.outline)

    # 如果第一个章节就没有分卷，全部归入未分卷（无需检查后续）
    has_unassigned = not parsed.chapters[0].volume_title if parsed.chapters else True
    if has_unassigned:
        first_chapter_id = None
        for chapter in parsed.chapters:
            cid = db.db.create_chapter(book_id, chapter.title, None)
            db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
            if first_chapter_id is None:
                first_chapter_id = cid
        return {"book_id": book_id, "first_chapter_id": first_chapter_id}

    existing_volumes = {str(v["title"]): int(v["id"]) for v in db.db.list_volumes(book_id)}
    first_chapter_id = None

    for chapter in parsed.chapters:
        vid = None
        if chapter.volume_title:
            vid = existing_volumes.get(chapter.volume_title)
            if vid is None:
                vid = db.db.create_volume(book_id, chapter.volume_title)
                existing_volumes[chapter.volume_title] = vid

        cid = db.db.create_chapter(book_id, chapter.title, vid)
        db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
        if first_chapter_id is None:
            first_chapter_id = cid

    return {"book_id": book_id, "first_chapter_id": first_chapter_id}
