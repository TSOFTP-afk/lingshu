"""临时调试脚本 — 验证写回行为"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.analysis.v3_writeback import writeback_v3_card
from novel_app.database import Database
from tests.fixtures.test_novel import get_test_novel

with TemporaryDirectory() as tmp:
    db = Database(Path(tmp) / "novels.db")
    db.initialize()
    novel = get_test_novel()
    book_id = db.create_book(novel["title"])
    for ch in novel["chapters"]:
        cid = db.create_chapter(book_id, ch["title"])
        db.update_chapter(cid, outline="", content=ch["content"])
    for c in novel["characters"]:
        db.create_character(book_id, c["name"])
    for w in novel["world_entries"]:
        eid = db.create_world_entry(book_id, w["name"], category=w["category"])
        db.update_world_entry(eid, name=w["name"], category=w["category"], content_text=w["content_text"])

    chars_before = {str(ch["name"]): str(ch["profile_data_json"] or "")[:120] for ch in db.list_characters(book_id)}
    print("BEFORE:", chars_before)

    chunker = SemanticChunker(target_chars=200, max_chars=500)
    pipeline = AnalysisPipelineV3(db, chunker=chunker)
    result = pipeline.start_run(book_id, use_ai=False)

    cards = db.list_analysis_cards(result.run_id)
    store = AnalysisStore(db)

    for card in cards:
        payload = json.loads(str(card["payload_json"] or "{}"))
        wt = str(payload.get("writeback_target") or "")
        if wt == "character":
            wf = payload.get("writeback_fields", {})
            card_uid = str(card["card_uid"])
            name = wf.get("name", "")
            pt = str(wf.get("profile_text", ""))[:80]
            print(f"Card {card_uid}: name={name}, profile_text={pt}")
            wb_result = writeback_v3_card(db, book_id, dict(card))
            print(f"  Writeback: success={wb_result.success}, detail={wb_result.detail}")
            if wb_result.success:
                # Check the character after writeback
                updated_ch = db.get_character(wb_result.applied_id)
                if updated_ch:
                    pdj = str(updated_ch["profile_data_json"] or "")
                    print(f"  profile_data_json supplements: {'supplements' in pdj}")
                    if "supplements" in pdj:
                        pdj_data = json.loads(pdj)
                        print(f"  supplements count: {len(pdj_data.get('supplements', []))}")
                store.apply_card(book_id, result.run_id, card_uid)

    chars_after = {str(ch["name"]): str(ch["profile_data_json"] or "")[:120] for ch in db.list_characters(book_id)}
    print("AFTER:", chars_after)

    for name in chars_before:
        before = chars_before[name].strip()
        after = chars_after.get(name, "").strip()
        print(f"  {name}: changed={before != after}")

    db.close()
