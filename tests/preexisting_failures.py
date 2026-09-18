"""阶段 0 存量失败隔离清单（2026-09-19 抢救基线）。

这里的每一条都是 baseline 之前就存在的真实失败（此前被测试收集错误掩盖，
2026-09-19 首次全量跑通时暴露，共 24 条）。它们按簇登记根因，由根 conftest.py
统一打 ``xfail(strict=False)``，使默认测试路径回绿的同时保持失败可见：

- 修复后该用例会以 XPASS 出现 → 应立即从本清单删除对应条目；
- 新增条目必须写明簇与根因，禁止无理由追加。

排期：各簇根因修复属于抢救方案阶段 1/3（见 docs/项目抢救方案_2026-09.md）。
"""

# nodeid -> (簇, 根因摘要)
PREEXISTING_FAILURES: dict[str, tuple[str, str]] = {
    # ── 簇 A：AI 超时/JSON 契约漂移 ──
    # ai_provider 调 _post_json_chat_completion(..., timeout=...) 而
    # novel_app/ai/client.py 的方法签名不收 timeout；超时分档实现（8000字→120s）
    # 与测试规格（180s/300s）不一致。
    "tests/test_ai_provider.py::test_ai_provider_records_structured_error_for_timeout": ("AI超时契约", "client 不收 timeout 参数"),
    "tests/test_ai_provider.py::test_ai_provider_splits_long_block_and_restores_coordinates": ("AI超时契约", "stub 不收 timeout 参数"),
    "tests/test_ai_provider.py::test_ai_provider_extract_facts_uses_windows_and_restores_coordinates": ("AI超时契约", "stub 不收 timeout 参数"),
    "tests/test_ai_timeout_tiers.py::test_very_long_text_returns_180s": ("AI超时契约", "分档实现 120s vs 规格 180s"),
    "tests/test_ai_timeout_tiers.py::test_huge_text_returns_300s": ("AI超时契约", "分档实现 vs 规格 300s 不一致"),
    "tests/test_ai_json_mode.py::test_skill_distill_prompt_overrides_remote_templates": ("AI超时契约", "JSON mode 契约漂移"),
    "tests/test_ai_json_mode.py::test_post_json_chat_completion_forces_deepseek_json_mode_contract": ("AI超时契约", "JSON mode 契约漂移"),
    "tests/test_v3_full_ai_integration.py::test_memory_compressor_ai_fallback": ("AI超时契约", "AI unavailable 级联"),
    "tests/test_v3_full_ai_integration.py::test_semantic_chunker_ai_mode": ("AI超时契约", "AI unavailable 级联"),
    "tests/test_e2e_v3_writeback.py::test_e2e_v3_pipeline_meta_and_audit": ("AI超时契约", "V3 管线 meta/audit 断言漂移"),
    # ── 簇 B：workspace / probe / ai-settings API schema 漂移 ──
    "tests/test_routers_workspace_probe.py::test_trigger_writing_probe_enabled_returns_drafts": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_list_writing_probe_drafts_isolated_per_chapter": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_list_drafts_includes_run_id": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_apply_summary_writes_to_chapter": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_apply_summary_rejects_empty_text": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_writeback_all_applies_character_drafts": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_routers_workspace_probe.py::test_trigger_probe_nonexistent_book_returns_404": ("probe API 漂移", "schema/响应结构变化"),
    "tests/test_workspace_api.py::test_workspace_analysis_runs_cards_reject_apply_and_refresh_artifacts": ("probe API 漂移", "分析卡片 API 漂移"),
    "tests/test_phase2_api.py::test_phase2_workspace_drawer_routes": ("probe API 漂移", "KeyError，drawer 路由断言过期"),
    "tests/test_reference_api_and_ai_settings.py::test_ai_settings_roundtrip_and_purpose_resolution": ("probe API 漂移", "ai-settings 往返断言过期"),
    "tests/test_reference_api_and_ai_settings.py::test_writing_probe_settings_roundtrip": ("probe API 漂移", "probe 设置断言过期"),
    "tests/test_reference_api_and_ai_settings.py::test_writing_probe_interval_clamped_to_range": ("probe API 漂移", "probe 设置断言过期"),
    # ── 簇 C：RAG / 数据层 ──
    "tests/test_rag_modules.py::TestChapterRetriever::test_remove_book_reference_source_removes_vector_and_bm25_records": ("RAG 清理", "删参考源未同步清 vector/bm25"),
    "test_database_extensions.py::DatabaseExtensionTests::test_v2_epoch_discards_legacy_structured_data_once": ("数据层", "v2 epoch 遗留数据清理语义漂移"),
    # ── 簇 D：测试间全局状态污染 ──
    # 单跑通过、全量按套件顺序跑必挂：自建临时 DB 并 reset_default_workspace_db，
    # 但被其他用例污染的全局状态（默认 provider/环境变量）破坏，阶段 1 排查污染源。
    "tests/test_v1_writeback_bookdata_verify.py::test_v1_writeback_bookdata_verify": ("测试隔离", "全量顺序下全局状态被污染"),
}
