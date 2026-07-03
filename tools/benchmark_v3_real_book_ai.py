from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
DEFAULT_SOURCE_DB = ROOT_DIR / "data" / "novels.db"
DEFAULT_OUTPUT_ROOT = ROOT_DIR / "tmp_v3_real_book_ai_benchmark"
DEFAULT_BOOK_ID = 16
DEFAULT_SAMPLES = (10, 50, 200)
NEXT_SAMPLE_MAX_SECONDS = 60 * 60
MENTION_BATCH_SIZE = 200

from novel_app.analysis.ai_provider import (
    AI_TEXT_WINDOW_CHARS,
    AI_TEXT_WINDOW_OVERLAP,
    iter_ai_text_windows,
)

CAPS = {
    "blocks_default_list": 500,
    "mentions_coreference": 5000,
    "mentions_fact_extraction": 5000,
    "entities_fact_extraction": 5000,
    "facts_card_events": 5000,
    "facts_memory_or_probes": 10000,
}


@dataclass(frozen=True)
class SourceBook:
    book_id: int
    title: str
    chapter_count: int
    char_count: int
    approx_blocks: int
    approx_ai_text_windows: int
    approx_min_block_ai_calls: int


class BenchmarkStop(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated V3 AI analysis benchmarks against a real local book.")
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--book-id", type=int, default=DEFAULT_BOOK_ID)
    parser.add_argument("--samples", default=",".join(str(item) for item in DEFAULT_SAMPLES))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--max-next-minutes", type=float, default=60.0)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Prepare reports and estimates without remote AI calls.")
    parser.add_argument("--ai-max-workers", type=int, default=4)
    parser.add_argument("--ai-timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    output_dir = args.output_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(args.source_db),
        "source_book_id": args.book_id,
        "output_dir": str(output_dir),
        "samples_requested": _parse_samples(args.samples),
        "dry_run": bool(args.dry_run),
        "preflight": {},
        "source_book": {},
        "sample_runs": [],
        "full_book_estimate": {},
        "stopped_reason": "",
    }

    try:
        source = inspect_source_book(args.source_db, args.book_id)
        log(f"source book {args.book_id}: {source.chapter_count} chapters, {source.char_count} chars")
        metrics["source_book"] = source.__dict__
        log("running preflight")
        metrics["preflight"] = run_preflight(args, output_dir)
        if not metrics["preflight"]["ok"]:
            raise BenchmarkStop("preflight failed")

        if args.dry_run:
            metrics["full_book_estimate"] = build_full_book_estimate(source, [])
            raise BenchmarkStop("dry run requested")

        sample_runs, stopped_reason = run_samples(args, output_dir, source)
        metrics["sample_runs"] = sample_runs
        if stopped_reason:
            metrics["stopped_reason"] = stopped_reason
        metrics["full_book_estimate"] = build_full_book_estimate(source, metrics["sample_runs"])
    except BenchmarkStop as exc:
        metrics["stopped_reason"] = str(exc)
        if not metrics.get("full_book_estimate"):
            source = SourceBook(**metrics["source_book"]) if metrics.get("source_book") else None
            metrics["full_book_estimate"] = build_full_book_estimate(source, metrics["sample_runs"]) if source else {}
    except Exception as exc:
        metrics["stopped_reason"] = f"failed: {exc}"
        metrics["error"] = str(exc)
        write_outputs(output_dir, metrics)
        raise

    write_outputs(output_dir, metrics)
    print(f"metrics: {output_dir / 'metrics.json'}")
    print(f"report:  {output_dir / 'report.md'}")
    return 0 if not str(metrics.get("stopped_reason", "")).startswith("failed:") else 1


def run_preflight(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "pytest_skipped": bool(args.skip_pytest),
        "pytest": [],
        "ai_profile": {},
    }
    if not args.skip_pytest:
        for test_path in (
            "tests/test_ai_provider.py",
            "tests/test_ai_json_mode.py",
            "tests/test_analysis_pipeline_v3.py",
        ):
            started = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_path, "-q"],
                cwd=ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=300,
            )
            test_result = {
                "path": test_path,
                "returncode": proc.returncode,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "stdout_tail": _tail(proc.stdout),
                "stderr_tail": _tail(proc.stderr),
            }
            result["pytest"].append(test_result)
            if proc.returncode != 0:
                result["ok"] = False

    ai_profile = resolve_book_analysis_profile()
    result["ai_profile"] = ai_profile
    if not ai_profile["ready"] and not args.dry_run:
        result["ok"] = False
    (output_dir / "preflight.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def resolve_book_analysis_profile() -> dict[str, Any]:
    from lingshu_api.services.ai_settings import resolve_ai_profile, validate_profile_ready

    profile = resolve_ai_profile(ROOT_DIR / "data", "book_analysis")
    ready, message = validate_profile_ready(profile)
    return {
        "ready": bool(ready),
        "message": message,
        "remote_enabled": bool(profile.get("remote_enabled")),
        "base_url": str(profile.get("base_url") or ""),
        "model": str(profile.get("model") or ""),
        "temperature": profile.get("temperature"),
        "max_tokens": profile.get("max_tokens"),
        "api_key_configured": bool(str(profile.get("api_key") or "").strip()),
    }


def run_samples(args: argparse.Namespace, output_dir: Path, source: SourceBook) -> tuple[list[dict[str, Any]], str]:
    runs: list[dict[str, Any]] = []
    samples = _parse_samples(args.samples)
    max_next_seconds = max(1.0, float(args.max_next_minutes) * 60.0)
    for index, chapter_limit in enumerate(samples):
        if runs:
            previous = runs[-1]
            if previous.get("status") != "probes_ready":
                return runs, f"previous sample failed before {chapter_limit} chapters"
            if float(previous.get("ai_error_rate") or 0.0) > 0.10:
                return runs, f"AI error rate exceeded 10 percent before {chapter_limit} chapters"
            estimated_next = estimate_next_sample_seconds(previous, chapter_limit)
            if estimated_next > max_next_seconds:
                return runs, f"estimated {chapter_limit}-chapter sample exceeds {args.max_next_minutes:g} minutes"

        sample_dir = output_dir / f"sample_{chapter_limit:04d}_chapters"
        sample_dir.mkdir(parents=True, exist_ok=True)
        log(f"starting sample: {chapter_limit} chapters")
        metrics = run_one_sample(
            source_db=args.source_db,
            source_book_id=args.book_id,
            source=source,
            chapter_limit=chapter_limit,
            sample_dir=sample_dir,
            ai_max_workers=args.ai_max_workers,
            ai_timeout_seconds=args.ai_timeout_seconds,
        )
        log(
            "completed sample: "
            f"{chapter_limit} chapters, status={metrics.get('status')}, "
            f"elapsed={metrics.get('wall_clock_seconds')}s, "
            f"ai_calls={metrics.get('ai_call_count')}, errors={metrics.get('ai_error_count')}"
        )
        runs.append(metrics)
        (sample_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        if index < len(samples) - 1 and float(metrics.get("ai_error_rate") or 0.0) > 0.10:
            return runs, f"AI error rate exceeded 10 percent after {chapter_limit} chapters"
    if runs and float(runs[-1].get("ai_error_rate") or 0.0) > 0.10:
        return runs, f"AI error rate exceeded 10 percent after {runs[-1].get('chapter_count')} chapters"
    return runs, ""


def run_one_sample(
    *,
    source_db: Path,
    source_book_id: int,
    source: SourceBook,
    chapter_limit: int,
    sample_dir: Path,
    ai_max_workers: int,
    ai_timeout_seconds: int,
) -> dict[str, Any]:
    patch_database_helpers()

    from lingshu_api.services.ai_settings import resolve_ai_profile
    from novel_app.ai.service import SimpleAIService
    from novel_app.analysis.ai_provider import AIAnalysisProvider
    from novel_app.analysis.llm_cache import LLMCache
    from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
    from novel_app.database import Database

    db_path = sample_dir / "novels.db"
    if db_path.exists():
        db_path.unlink()
    db = Database(db_path)
    ai_provider = None
    started = time.perf_counter()
    try:
        db.initialize()
        book_id, copied = copy_sample_to_temp_db(source_db, source_book_id, db, chapter_limit)
        profile = resolve_ai_profile(ROOT_DIR / "data", "book_analysis")
        ai_service = SimpleAIService()
        os.environ.setdefault("LINGSHU_AI_TIMEOUT", str(max(1, int(ai_timeout_seconds))))
        ai_service.configure(
            api_key=profile.get("api_key") or None,
            base_url=profile.get("base_url") or None,
            model=profile.get("model") or None,
        )
        ai_service._request_timeout = max(1, int(ai_timeout_seconds))
        ai_service.require_remote("V3 AI benchmark")
        ai_provider = AIAnalysisProvider(ai_service, LLMCache(db))

        def progress(stage: str, percent: int, message: str) -> None:
            log(f"sample {chapter_limit} progress {percent}% {stage}: {message}")

        result = AnalysisPipelineV3(db, ai_provider=ai_provider).start_run(
            book_id,
            use_ai=True,
            ai_max_workers=ai_max_workers,
            progress_callback=progress,
            meta={
                "source": "benchmark_v3_real_book_ai",
                "source_book_id": source_book_id,
                "sample_chapter_limit": chapter_limit,
            },
        )
        elapsed = time.perf_counter() - started
        metrics = collect_run_metrics(db, book_id, result.run_id, result.as_dict(), copied, elapsed, ai_provider)
        metrics["source_book_total_chapters"] = source.chapter_count
        metrics["source_book_total_chars"] = source.char_count
        metrics["sample_dir"] = str(sample_dir)
        metrics["temp_db"] = str(db_path)
        metrics["ai_timeout_seconds"] = max(1, int(ai_timeout_seconds))
        return metrics
    finally:
        db.close()


def copy_sample_to_temp_db(source_db: Path, source_book_id: int, db: Any, chapter_limit: int) -> tuple[int, dict[str, Any]]:
    with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        book = source.execute(
            "SELECT id, title, outline_text, world_text FROM books WHERE id = ?",
            (source_book_id,),
        ).fetchone()
        if not book:
            raise RuntimeError(f"source book {source_book_id} not found")

        chapters = source.execute(
            """
            SELECT id, title, outline, content, summary_text, sort_order
            FROM chapters
            WHERE book_id = ?
            ORDER BY sort_order ASC, id ASC
            LIMIT ?
            """,
            (source_book_id, max(1, int(chapter_limit))),
        ).fetchall()

    if not chapters:
        raise RuntimeError(f"source book {source_book_id} has no chapters")

    book_id = db.create_book(str(book["title"] or f"book-{source_book_id}"))
    if str(book["outline_text"] or "").strip():
        db.update_book_outline(book_id, str(book["outline_text"] or ""))
    if str(book["world_text"] or "").strip():
        db.update_book_world(book_id, str(book["world_text"] or ""))

    total_chars = 0
    max_chapter_chars = 0
    for chapter in chapters:
        content = str(chapter["content"] or "")
        total_chars += len(content)
        max_chapter_chars = max(max_chapter_chars, len(content))
        chapter_id = db.create_chapter(book_id, str(chapter["title"] or f"chapter-{chapter['id']}"))
        db.update_chapter(
            chapter_id,
            outline=str(chapter["outline"] or ""),
            content=content,
            summary_text=str(chapter["summary_text"] or ""),
        )

    return book_id, {
        "chapter_count": len(chapters),
        "char_count": total_chars,
        "max_chapter_chars": max_chapter_chars,
    }


def collect_run_metrics(
    db: Any,
    book_id: int,
    run_id: int,
    result: dict[str, Any],
    copied: dict[str, Any],
    elapsed: float,
    ai_provider: Any,
) -> dict[str, Any]:
    counts = {
        "blocks": count_rows(db, "analysis_blocks", book_id, run_id),
        "mentions": count_rows(db, "analysis_entity_mentions", book_id, run_id),
        "entities": count_rows(db, "analysis_entities", book_id, run_id),
        "facts": count_rows(db, "analysis_facts", book_id, run_id),
        "cards": count_rows(db, "analysis_cards", book_id, run_id),
        "events": count_rows(db, "analysis_events", book_id, run_id),
        "probe_plans": count_rows(db, "analysis_probe_plans", book_id, run_id),
        "probe_results": count_rows(db, "analysis_probe_results", book_id, run_id),
    }
    block_lengths = [
        int(row["text_len"] or 0)
        for row in db.connection.execute(
            "SELECT LENGTH(COALESCE(text, '')) AS text_len FROM analysis_blocks WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        ).fetchall()
    ]
    ai_error_count = len(getattr(ai_provider, "errors", []) or [])
    ai_call_count = int(result.get("meta", {}).get("ai_call_count") or getattr(ai_provider, "call_count", 0) or 0)
    ai_cache_hits = int(result.get("meta", {}).get("ai_cache_hits") or getattr(ai_provider, "cache_hits", 0) or 0)
    repaired_json_count = int(getattr(ai_provider, "repaired_json_count", 0) or 0)
    retry_count = int(getattr(ai_provider, "retry_count", 0) or 0)
    error_type_counts = dict(getattr(ai_provider, "error_type_counts", {}) or {})
    ai_attempt_denominator = max(1, ai_call_count + ai_cache_hits + ai_error_count)
    coverage = ai_text_coverage(block_lengths)
    downstream_caps = cap_risks(counts)
    core_outputs_nonempty = (
        counts["blocks"] > 0
        and counts["mentions"] > 0
        and counts["entities"] > 0
        and counts["facts"] > 0
        and counts["cards"] > 0
    )
    expected_remote_calls = (
        (2 * int(coverage.get("window_count") or counts["blocks"]))
        + math.ceil(counts["mentions"] / MENTION_BATCH_SIZE)
        + counts["probe_plans"]
    )
    ai_error_rate = ai_error_count / ai_attempt_denominator
    usable = (
        result.get("status") == "probes_ready"
        and bool(result.get("meta", {}).get("ai_invoked"))
        and ai_call_count > 0
        and core_outputs_nonempty
        and coverage["coverage_ratio"] >= 0.95
        and not downstream_caps["any_triggered"]
        and ai_error_rate <= 0.10
    )
    return {
        "run_id": run_id,
        "book_id": book_id,
        "chapter_count": copied["chapter_count"],
        "char_count": copied["char_count"],
        "max_chapter_chars": copied["max_chapter_chars"],
        "status": result.get("status"),
        "wall_clock_seconds": round(elapsed, 3),
        "seconds_per_10k_chars": round(elapsed / max(1, copied["char_count"]) * 10000, 3),
        "seconds_per_block": round(elapsed / max(1, counts["blocks"]), 3),
        "counts": counts,
        "block_count": counts["blocks"],
        "mention_count": counts["mentions"],
        "entity_count": counts["entities"],
        "fact_count": counts["facts"],
        "card_count": counts["cards"],
        "probe_plan_count": counts["probe_plans"],
        "probe_result_count": counts["probe_results"],
        "ai_invoked": bool(result.get("meta", {}).get("ai_invoked")),
        "ai_stages": result.get("meta", {}).get("ai_stages", []),
        "ai_fallback_stages": result.get("meta", {}).get("ai_fallback_stages", []),
        "ai_call_count": ai_call_count,
        "ai_cache_hits": ai_cache_hits,
        "ai_error_count": ai_error_count,
        "ai_error_rate": round(ai_error_rate, 4),
        "repaired_json_count": repaired_json_count,
        "retry_count": retry_count,
        "error_type_counts": error_type_counts,
        "ai_error_samples": list(getattr(ai_provider, "errors", []) or [])[:20],
        "expected_remote_call_estimate": expected_remote_calls,
        "expected_remote_call_formula": "2 * ai_text_window_count + ceil(mentions/200) + probe_plan_count",
        "ai_text_coverage": coverage,
        "downstream_caps": downstream_caps,
        "core_outputs_nonempty": core_outputs_nonempty,
        "usable": usable,
        "usability_verdict": "usable" if usable else "runs_but_has_real_usability_gaps",
        "meta": result.get("meta", {}),
    }


def count_rows(db: Any, table: str, book_id: int, run_id: int) -> int:
    row = db.connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE book_id = ? AND run_id = ?",
        (book_id, run_id),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def ai_text_coverage(block_lengths: list[int]) -> dict[str, Any]:
    total = sum(max(0, item) for item in block_lengths)
    read = 0
    window_count = 0
    coverage_by_block: list[dict[str, Any]] = []
    coverage_by_window: list[dict[str, Any]] = []
    for block_index, raw_length in enumerate(block_lengths):
        length = max(0, int(raw_length))
        windows = iter_ai_text_windows("x" * length)
        window_count += len(windows)
        ranges = [(window.start, window.end) for window in windows]
        visible = _covered_chars(ranges)
        read += visible
        coverage_by_block.append(
            {
                "block_index": block_index,
                "block_chars": length,
                "window_count": len(windows),
                "visible_chars": visible,
                "coverage_ratio": round(visible / length, 6) if length else 1.0,
            }
        )
        for window in windows:
            coverage_by_window.append(
                {
                    "block_index": block_index,
                    "window_index": window.index,
                    "window_start": window.start,
                    "window_end": window.end,
                    "window_chars": window.end - window.start,
                }
            )
    long_blocks = sum(1 for item in block_lengths if item > AI_TEXT_WINDOW_CHARS)
    return {
        "window_chars": AI_TEXT_WINDOW_CHARS,
        "window_overlap_chars": AI_TEXT_WINDOW_OVERLAP,
        "total_block_chars": total,
        "ai_visible_chars": read,
        "coverage_ratio": round(read / total, 6) if total else 1.0,
        "long_block_count": long_blocks,
        "block_count": len(block_lengths),
        "window_count": window_count,
        "coverage_by_block": coverage_by_block,
        "coverage_by_window": coverage_by_window,
    }


def _covered_chars(ranges: list[tuple[int, int]]) -> int:
    if not ranges:
        return 0
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
    return sum(max(0, end - start) for start, end in merged)


def cap_risks(counts: dict[str, int]) -> dict[str, Any]:
    legacy_thresholds = {
        "blocks_exceed_default_list_500": counts["blocks"] > CAPS["blocks_default_list"],
        "mentions_exceed_coreference_5000": counts["mentions"] > CAPS["mentions_coreference"],
        "mentions_exceed_fact_extraction_5000": counts["mentions"] > CAPS["mentions_fact_extraction"],
        "entities_exceed_fact_extraction_5000": counts["entities"] > CAPS["entities_fact_extraction"],
        "facts_exceed_card_events_5000": counts["facts"] > CAPS["facts_card_events"],
        "facts_exceed_memory_or_probes_10000": counts["facts"] > CAPS["facts_memory_or_probes"],
    }
    risks = {
        **legacy_thresholds,
        "legacy_threshold_exceeded": legacy_thresholds,
        "internal_pipeline_limit_none": True,
        "any_triggered": False,
        "caps": CAPS,
    }
    return risks


def inspect_source_book(source_db: Path, book_id: int) -> SourceBook:
    with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT b.id, b.title, COUNT(c.id) AS chapter_count,
                   SUM(LENGTH(COALESCE(c.content, ''))) AS char_count
            FROM books b
            LEFT JOIN chapters c ON c.book_id = b.id
            WHERE b.id = ?
            GROUP BY b.id, b.title
            """,
            (book_id,),
        ).fetchone()
    if not row:
        raise RuntimeError(f"source book {book_id} not found in {source_db}")
    chars = int(row["char_count"] or 0)
    blocks = math.ceil(chars / 6000)
    window_stride = max(1, AI_TEXT_WINDOW_CHARS - AI_TEXT_WINDOW_OVERLAP)
    approx_windows = max(blocks, math.ceil(chars / window_stride))
    return SourceBook(
        book_id=int(row["id"]),
        title=str(row["title"] or ""),
        chapter_count=int(row["chapter_count"] or 0),
        char_count=chars,
        approx_blocks=blocks,
        approx_ai_text_windows=approx_windows,
        approx_min_block_ai_calls=approx_windows * 2,
    )


def estimate_next_sample_seconds(previous: dict[str, Any], next_chapter_limit: int) -> float:
    current_chapters = max(1, int(previous.get("chapter_count") or 1))
    return float(previous.get("wall_clock_seconds") or 0.0) * (max(1, next_chapter_limit) / current_chapters)


def build_full_book_estimate(source: SourceBook | None, runs: list[dict[str, Any]]) -> dict[str, Any]:
    if source is None:
        return {}
    estimate: dict[str, Any] = {
        "source_chapters": source.chapter_count,
        "source_chars": source.char_count,
        "approx_blocks_6000_chars": source.approx_blocks,
        "approx_ai_text_windows": source.approx_ai_text_windows,
        "approx_min_block_ai_calls": source.approx_min_block_ai_calls,
        "method": "no completed sample; static approximation only",
    }
    completed = [run for run in runs if run.get("status") == "probes_ready" and run.get("wall_clock_seconds")]
    if not completed:
        return estimate

    basis = completed[-1]
    sec = float(basis["wall_clock_seconds"])
    chars = max(1, int(basis.get("char_count") or 1))
    blocks = max(1, int(basis.get("block_count") or 1))
    calls = max(1, int(basis.get("ai_call_count") or basis.get("expected_remote_call_estimate") or 1))
    char_based = sec / chars * source.char_count
    block_based = sec / blocks * source.approx_blocks
    call_based = sec / calls * max(source.approx_min_block_ai_calls, source.approx_blocks * 2)
    values = [char_based, block_based, call_based]
    estimate.update(
        {
            "method": f"extrapolated from {basis.get('chapter_count')} chapter sample",
            "basis_run_id": basis.get("run_id"),
            "seconds_by_chars": round(char_based, 1),
            "seconds_by_blocks": round(block_based, 1),
            "seconds_by_ai_calls": round(call_based, 1),
            "conservative_seconds_min": round(min(values), 1),
            "conservative_seconds_max": round(max(values) * 1.25, 1),
            "conservative_hours_min": round(min(values) / 3600, 2),
            "conservative_hours_max": round(max(values) * 1.25 / 3600, 2),
        }
    )
    return estimate


def write_outputs(output_dir: Path, metrics: dict[str, Any]) -> None:
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(metrics), encoding="utf-8")


def render_report(metrics: dict[str, Any]) -> str:
    source = metrics.get("source_book", {})
    lines = [
        "# V3 Real Book AI Benchmark Report",
        "",
        "## Source",
        f"- Source DB: `{metrics.get('source_db', '')}`",
        f"- Book ID: `{metrics.get('source_book_id', '')}`",
        f"- Chapters: {source.get('chapter_count', 0)}",
        f"- Text characters: {source.get('char_count', 0)}",
        f"- Approx blocks at 6000 chars: {source.get('approx_blocks', 0)}",
        f"- Approx AI text windows: {source.get('approx_ai_text_windows', 0)}",
        "- Body text is not included in this report.",
        "",
        "## Preflight",
    ]
    preflight = metrics.get("preflight", {})
    lines.append(f"- OK: {bool(preflight.get('ok'))}")
    profile = preflight.get("ai_profile", {})
    if profile:
        lines.extend(
            [
                f"- AI ready: {bool(profile.get('ready'))}",
                f"- Base URL: `{profile.get('base_url', '')}`",
                f"- Model: `{profile.get('model', '')}`",
                f"- API key configured: {bool(profile.get('api_key_configured'))}",
            ]
        )
    for item in preflight.get("pytest", []):
        lines.append(f"- `{item.get('path')}`: rc={item.get('returncode')} elapsed={item.get('elapsed_seconds')}s")

    lines.extend(["", "## Sample Runs"])
    runs = metrics.get("sample_runs", [])
    if not runs:
        lines.append("- No sample completed.")
    for run in runs:
        coverage = run.get("ai_text_coverage", {})
        caps = run.get("downstream_caps", {})
        lines.extend(
            [
                f"### {run.get('chapter_count')} chapters",
                f"- Status: `{run.get('status')}`; verdict: `{run.get('usability_verdict')}`",
                f"- Chars: {run.get('char_count')}; blocks: {run.get('block_count')}; elapsed: {run.get('wall_clock_seconds')}s",
                f"- AI calls/cache/errors: {run.get('ai_call_count')}/{run.get('ai_cache_hits')}/{run.get('ai_error_count')} "
                f"(error rate {run.get('ai_error_rate')})",
                f"- AI retries/repaired JSON/error types: {run.get('retry_count', 0)}/{run.get('repaired_json_count', 0)}/"
                f"{run.get('error_type_counts', {})}",
                f"- Outputs: mentions={run.get('mention_count')}, entities={run.get('entity_count')}, "
                f"facts={run.get('fact_count')}, cards={run.get('card_count')}, probes={run.get('probe_plan_count')}",
                f"- AI text coverage: {coverage.get('coverage_ratio')} "
                f"({coverage.get('ai_visible_chars')}/{coverage.get('total_block_chars')} chars, "
                f"{coverage.get('window_count')} windows, {coverage.get('long_block_count')} blocks over "
                f"{coverage.get('window_chars')} chars)",
                f"- Downstream cap triggered: {bool(caps.get('any_triggered'))}",
            ]
        )

    estimate = metrics.get("full_book_estimate", {})
    lines.extend(
        [
            "",
            "## Full Book Estimate",
            f"- Method: {estimate.get('method', '')}",
            f"- Approx AI text windows: {estimate.get('approx_ai_text_windows', 0)}",
            f"- Approx remote window calls: {estimate.get('approx_min_block_ai_calls', 0)} plus coreference/probe calls",
            f"- Estimated hours: {estimate.get('conservative_hours_min', 'n/a')} - {estimate.get('conservative_hours_max', 'n/a')}",
            "",
            "## Notes",
            "- A run is marked usable only when status is probes_ready, AI was invoked, core outputs are non-empty, "
            "AI text coverage is at least 95%, no downstream cap is triggered, and AI error rate is at most 10%.",
            "- AI text coverage is calculated from the provider windowing settings, not from exported body text.",
        ]
    )
    if metrics.get("stopped_reason"):
        lines.extend(["", "## Stop Reason", f"- {metrics['stopped_reason']}"])
    return "\n".join(lines) + "\n"


def patch_database_helpers() -> None:
    from novel_app.database import Database

    if not hasattr(Database, "query_one"):
        def _query_one(self: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
            return self.connection.execute(sql, params).fetchone()

        Database.query_one = _query_one  # type: ignore[attr-defined]
    if not hasattr(Database, "execute"):
        def _execute(self: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
            return self.connection.execute(sql, params)

        Database.execute = _execute  # type: ignore[attr-defined]


def _parse_samples(value: str) -> list[int]:
    samples = []
    for item in str(value or "").split(","):
        item = item.strip()
        if item:
            samples.append(max(1, int(item)))
    return samples or list(DEFAULT_SAMPLES)


def _tail(text: str, lines: int = 40) -> str:
    parts = str(text or "").splitlines()
    return "\n".join(parts[-lines:])


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
