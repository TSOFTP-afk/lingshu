from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


FORMAL_WRITEBACK_KEYS = {
    "book_outline",
    "book_outline_form",
    "world_form",
    "world_text",
    "world_entries",
    "characters",
    "chapter_updates",
}


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _has_content(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return True


def _has_formal_content(payload: dict[str, Any]) -> bool:
    return any(_has_content(payload.get(key)) for key in FORMAL_WRITEBACK_KEYS)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def scan_database(db_path: Path) -> list[dict[str, Any]]:
    with _connect_readonly(db_path) as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if not {"analysis_runs", "analysis_cards"}.issubset(tables):
            return []
        rows = connection.execute(
            """
            SELECT
                runs.id AS run_id,
                runs.book_id AS book_id,
                runs.status AS run_status,
                runs.summary AS run_summary,
                runs.meta_json AS run_meta_json,
                books.title AS book_title,
                cards.id AS card_id,
                cards.status AS card_status,
                cards.payload_json AS payload_json,
                cards.diff_json AS diff_json
            FROM analysis_runs AS runs
            JOIN analysis_cards AS cards ON cards.run_id = runs.id AND cards.card_type = 'full_payload'
            LEFT JOIN books ON books.id = runs.book_id
            ORDER BY runs.id DESC
            """
        ).fetchall()

    reports: list[dict[str, Any]] = []
    for row in rows:
        payload = _json_object(row["payload_json"])
        diff = _json_object(row["diff_json"])
        run_meta = _json_object(row["run_meta_json"])
        gate = diff.get("evidence_writeback_gate")
        if not isinstance(gate, dict):
            gate = run_meta.get("writeback_gate")
        if not isinstance(gate, dict):
            gate = run_meta.get("last_writeback_gate")
        if not isinstance(gate, dict):
            gate = {}
        payload_meta = payload.get("_meta", {}) if isinstance(payload.get("_meta"), dict) else {}
        dropped = int(payload_meta.get("evidence_gate_dropped", 0) or 0)
        gate_status = str(gate.get("status") or "").strip()
        is_empty_gate_failure = gate_status == "empty" and dropped > 0
        if not is_empty_gate_failure:
            continue
        has_formal_content = _has_formal_content(payload)
        reports.append(
            {
                "run_id": int(row["run_id"]),
                "book_id": int(row["book_id"]),
                "book_title": str(row["book_title"] or row["book_id"]),
                "run_status": str(row["run_status"] or ""),
                "run_summary": str(row["run_summary"] or ""),
                "card_id": int(row["card_id"]),
                "card_status": str(row["card_status"] or ""),
                "gate_status": gate_status,
                "gate_reason": str(gate.get("reason") or ""),
                "evidence_gate_dropped": dropped,
                "payload_keys": sorted(payload.keys()),
                "has_formal_content": has_formal_content,
                "recoverable_from_saved_payload": has_formal_content,
                "advice": (
                    "saved payload still has formal fields; new weak-evidence flow can apply after user confirmation"
                    if has_formal_content
                    else "saved payload has already been pruned; rerun whole-book analysis after the fix"
                ),
            }
        )
    return reports


def _book_design_markdown(database: Any, book_id: int) -> tuple[str, str]:
    book = database.get_book(book_id)
    if not book:
        return str(book_id), ""
    character_blocks: list[str] = []
    for character in database.list_characters(book_id):
        name = str(character["name"] or "").strip()
        role = str(character["role"] or "").strip()
        profile = str(character["profile_text"] or "").strip()
        if profile:
            heading = f"### {name}" + (f"（{role}）" if role else "")
            character_blocks.append(f"{heading}\n\n{profile}")
    character_markdown = "\n\n".join(character_blocks)
    markdown = (
        f"{str(book['outline_text'] or '').strip()}"
        f"\n\n## 世界观设定\n{str(book['world_text'] or '').strip()}"
        f"\n\n## 人物卡设定\n{character_markdown}"
    ).strip()
    return str(book["title"] or book_id), markdown


def resync_truth_and_rag(db_path: Path, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["SIMPLE_AI_NOVEL_DATA_DIR"] = str(db_path.resolve().parent)
    from novel_app.database import Database
    from novel_app.rag import ChapterRetriever
    from novel_app.truth import TruthManager

    affected_book_ids = sorted({int(item["book_id"]) for item in reports})
    results: list[dict[str, Any]] = []
    database = Database(db_path)
    try:
        truth_manager = TruthManager(database.data_dir, database)
        retriever = ChapterRetriever(database.data_dir / "rag_vectors")
        for book_id in affected_book_ids:
            title, markdown = _book_design_markdown(database, book_id)
            truth_files = truth_manager.build_all(book_id)
            if truth_files:
                retriever.index_truth_snapshot(book_id, title, truth_files)
            if markdown:
                retriever.index_book_design(book_id, title, markdown)
            results.append(
                {
                    "book_id": book_id,
                    "book_title": title,
                    "truth_files": sorted(truth_files.keys()),
                    "rag_resynced": bool(truth_files or markdown),
                }
            )
    finally:
        database.close()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose whole-book analysis drafts blocked by empty evidence gates.")
    parser.add_argument("--db", default="data/novels.db", help="Path to novels.db")
    parser.add_argument("--apply", action="store_true", help="Resync current formal Truth/RAG for affected books")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 2

    reports = scan_database(db_path)
    result: dict[str, Any] = {
        "db_path": str(db_path),
        "affected_runs": reports,
        "affected_run_count": len(reports),
        "note": "Pruned saved payloads cannot restore removed AI fields; rerun analysis after applying the code fix.",
    }
    if args.apply:
        result["resync"] = resync_truth_and_rag(db_path, reports) if reports else []

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"数据库：{db_path}")
    print(f"发现 empty gate + evidence_gate_dropped 的运行：{len(reports)}")
    for item in reports:
        print(
            f"- run #{item['run_id']} / book #{item['book_id']}《{item['book_title']}》："
            f"剔除 {item['evidence_gate_dropped']} 项，"
            f"{'可从已保存 payload 手动应用' if item['recoverable_from_saved_payload'] else '旧草案字段已被剔除，需重新分析'}"
        )
    if args.apply:
        for item in result.get("resync", []):
            print(f"已重建 Truth/RAG：book #{item['book_id']}《{item['book_title']}》")
    else:
        print("默认只读；如需仅重建当前正式 Truth/RAG，请加 --apply。")
    print("注意：已被旧逻辑删除且未保存的原始 AI 字段无法恢复。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
