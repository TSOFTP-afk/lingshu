"""AIMD V3 verification test — real environment run on book 6 with use_ai=True.

Mirrors the WS analysis_v3 path: stop service -> run -> start service.
Logs AIMD slow-start ramp + M2/M4 (ai_mention / ai_fact) concurrency control.
"""
import os
import sys
import time
import logging
import traceback
from datetime import datetime

os.environ.setdefault('SIMPLE_AI_NOVEL_DATA_DIR', '/home/CODEX/lingshu-cloud/data')
os.environ.setdefault('BOOKSTORE_DB_PATH', '/home/CODEX/lingshu-cloud/data/bookstore_demo.db')

sys.path.insert(0, '/home/CODEX/lingshu-cloud/app')

# Capture AIMD progress logs (run_aimd_pool emits logger.info with concurrency/peak)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)
for _noisy in ('urllib3', 'httpx', 'httpcore', 'openai', 'sentence_transformers', 'chromadb'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

from lingshu_api.services.db_bridge import WorkspaceDB
from lingshu_api.ws.generation import _create_ai_service
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3, AI_MAX_WORKERS
from novel_app.analysis.ai_provider import AIAnalysisProvider, AI_COREFERENCE_CONCURRENCY_MAX
from novel_app.analysis.llm_cache import LLMCache

BOOK_ID = 6
USER_ID = 1

print('=' * 70)
print('AIMD V3 verification test')
print('=' * 70)
print('AI_MAX_WORKERS =', AI_MAX_WORKERS)
print('AI_COREFERENCE_CONCURRENCY_MAX =', AI_COREFERENCE_CONCURRENCY_MAX)
print('book_id =', BOOK_ID, 'user_id =', USER_ID)
print('start time:', datetime.now().isoformat(), flush=True)

t0 = time.monotonic()
stages_seen = []


def progress_cb(stage, percent, message):
    elapsed = time.monotonic() - t0
    stages_seen.append((round(elapsed, 1), stage, percent, str(message)))
    print('PROGRESS %.1fs stage=%s percent=%s msg=%s' % (elapsed, stage, percent, message), flush=True)


wdb = WorkspaceDB()
print('WorkspaceDB ready, data_dir =', wdb.db.data_dir, flush=True)

# Load chapters (mirror analysis_v3_ws._load_chapters)
chapters = []
for row in wdb.list_chapters(BOOK_ID):
    chapter = wdb.get_chapter(int(row['id']))
    if chapter and str(chapter.get('content') or '').strip():
        chapters.append(chapter)
total_chars = sum(len(str(c.get('content') or '')) for c in chapters)
print('loaded %d chapters, %d chars' % (len(chapters), total_chars), flush=True)
if not chapters:
    print('ERROR: no chapters loaded for book_id=%d' % BOOK_ID)
    wdb.close()
    sys.exit(2)

# Build AI service from user 001 book_analysis profile
ai_service = _create_ai_service('book_analysis', workspace_db=wdb, user_id=USER_ID)
ai_service.require_remote('V3 AI 增强分析')
print('AI service ready, model =', getattr(ai_service, 'model', None), flush=True)

ai_provider = AIAnalysisProvider(ai_service, LLMCache(wdb.db), database=wdb.db)
pipeline = AnalysisPipelineV3(wdb.db, ai_provider=ai_provider)
print('pipeline built, starting run with use_ai=True ...', flush=True)

try:
    result = pipeline.start_run(
        BOOK_ID,
        chapters=chapters,
        execute_l1=True,
        meta={'source': 'test_aimd_v3', 'ai_invoked': True},
        progress_callback=progress_cb,
        use_ai=True,
        cancel_event=None,
    )
    elapsed = time.monotonic() - t0
    print('=' * 70, flush=True)
    print('RUN COMPLETED in %.1fs' % elapsed, flush=True)
    print('status =', result.status)
    print('run_id =', result.run_id)
    print('block_count =', result.block_count)
    print('mention_count =', result.mention_count)
    print('entity_count =', result.entity_count)
    print('fact_count =', result.fact_count)
    print('card_count =', result.card_count)
    print('memory_fact_count =', result.memory_fact_count)
    print('probe_plan_count =', result.probe_plan_count)
    print('summary =', result.summary)
    print('meta ai_stages =', result.meta.get('ai_stages'))
    print('meta ai_fallback_stages =', result.meta.get('ai_fallback_stages'))
    print('meta ai_call_count =', result.meta.get('ai_call_count'))
    print('meta ai_cache_hits =', result.meta.get('ai_cache_hits'))
except Exception as exc:
    elapsed = time.monotonic() - t0
    print('=' * 70, flush=True)
    print('RUN FAILED in %.1fs' % elapsed, flush=True)
    print('error:', repr(exc), flush=True)
    traceback.print_exc()
    print('stages seen before failure:', flush=True)
    for s in stages_seen:
        print('  ', s, flush=True)
    raise
finally:
    try:
        wdb.close()
    except Exception:
        pass
    print('end time:', datetime.now().isoformat(), flush=True)
