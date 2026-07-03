from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from novel_app.analysis.schemas_v3 import stable_hash
from novel_app.database import Database
from novel_app.rag.retriever import ChapterRetriever

logger = logging.getLogger(__name__)

_ACTIVE_PROBE_SYSTEM_PROMPT = (
  "你是一个小说分析助手。用户正在查找小说中的某段剧情。"
  "请根据以下检索到的内容，回答用户的问题。"
)

_ACTIVE_PROBE_USER_TEMPLATE = (
  "用户问题：{query}\n\n"
  "检索到的内容：\n{context}\n\n"
  "请用以下 JSON 格式回答：\n"
  "{{\n"
  '  "summary": "对用户问题的总结性回答",\n'
  '  "references": [\n'
  '    {{"chapter_id": 章节ID, "title": "章节标题", "relevance": "与问题的关联说明"}}\n'
  "  ],\n"
  '  "confidence": 0.8\n'
  "}}"
)


class ActiveProbeExecutor:
  def __init__(
    self,
    database: Database,
    *,
    retriever: ChapterRetriever | None = None,
    ai_provider: Any | None = None,
  ) -> None:
    self.database = database
    self.retriever = retriever
    self.ai_provider = ai_provider

  def execute(
    self,
    *,
    book_id: int,
    query: str,
    run_id: int | None = None,
  ) -> dict[str, Any]:
    """执行主动探针

    1. 用 ChapterRetriever.search 检索相关内容
    2. 用 build_context_from_results 组装上下文
    3. 调用 LLM 生成结构化总结
    4. 返回结构化结果
    """
    results: list[dict[str, Any]] = []
    context_text = ""
    if self.retriever is not None:
      try:
        results = self.retriever.search(book_id, query, top_k=8, use_hybrid=True)
        context_text = self.retriever.build_context_from_results(results, max_chars=3000)
      except Exception:
        logger.exception("Active probe RAG search failed for book_id=%s", book_id)

    llm_result = self._call_llm(query, context_text)

    probe_uid = f"PROBE-ACTIVE-{stable_hash(f'active|{book_id}|{query}')[:16]}"

    _plan = {
      "probe_uid": probe_uid,
      "probe_type": "active_search",
      "probe_mode": "active",
      "subject_entity_uid": f"BOOK-{book_id}::ACTIVE-SEARCH",
      "plan": {
        "probe_uid": probe_uid,
        "probe_type": "active_search",
        "question": query,
        "expected": "LLM 根据检索内容回答用户查询",
        "subject": {
          "entity_uid": f"BOOK-{book_id}",
          "name": "主动探针",
          "entity_type": "book",
        },
        "source_evidence": [
          {
            "fact_uid": str(r.get("id", "")),
            "summary": str(r.get("payload", {}).get("summary", "")),
          }
          for r in results[:5]
        ],
        "target_evidence": [],
        "metadata": {
          "planner": "active_probe_v1",
          "formal_writeback": False,
          "manual_review_only": False,
        },
      },
      "status": "executed",
      "priority": 100,
    }

    _result = {
      "probe_uid": probe_uid,
      "probe_type": "active_search",
      "probe_mode": "active",
      "consistency": "consistent",
      "confidence": llm_result.get("confidence", 0.7),
      "status": "completed",
      "result": {
        "probe_type": "active_search",
        "finding": llm_result.get("summary", ""),
        "references": llm_result.get("references", []),
        "query": query,
        "rag_context_length": len(context_text),
      },
    }

    return {
      "ok": True,
      "query": query,
      "summary": llm_result.get("summary", ""),
      "references": llm_result.get("references", []),
      "confidence": llm_result.get("confidence", 0.7),
      "rag_results_count": len(results),
      "created_at": datetime.now(timezone.utc).isoformat(),
    }

  def _call_llm(self, query: str, context_text: str) -> dict[str, Any]:
    if self.ai_provider is None:
      return self._fallback_result(context_text)
    if not context_text.strip():
      return {"summary": "未检索到相关内容。", "references": [], "confidence": 0.3}
    try:
      messages = [
        {"role": "system", "content": _ACTIVE_PROBE_SYSTEM_PROMPT},
        {
          "role": "user",
          "content": _ACTIVE_PROBE_USER_TEMPLATE.format(
            query=query, context=context_text,
          ),
        },
      ]
      raw_response = self.ai_provider._post_json_chat_completion(
        messages=messages,
        temperature=0.3,
      )
      raw_text = self.ai_provider._chat_completion_content(raw_response, "主动探针")
      parsed = self.ai_provider._extract_json_object_payload(raw_text)
      if isinstance(parsed, dict) and parsed.get("summary"):
        return {
          "summary": str(parsed.get("summary", "")),
          "references": parsed.get("references") if isinstance(parsed.get("references"), list) else [],
          "confidence": float(parsed.get("confidence", 0.7)),
        }
      return self._fallback_result(context_text)
    except Exception:
      logger.exception("Active probe LLM call failed")
      return self._fallback_result(context_text)

  @staticmethod
  def _fallback_result(context_text: str) -> dict[str, Any]:
    return {
      "summary": (context_text[:500] + "...") if len(context_text) > 500 else context_text,
      "references": [],
      "confidence": 0.3,
    }
