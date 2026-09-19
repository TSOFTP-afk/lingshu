from __future__ import annotations

import shutil
import sqlite3
from typing import Any

from novel_app.db import migrations
from novel_app.db.common import (
    ANALYSIS_V3_FOUNDATION_MIGRATION_ID,
    BOOK_OUTLINE_FORM_MIGRATION_ID,
    CHARACTER_PROFILE_FORM_MIGRATION_ID,
    DATABASE_RESET_EPOCH_ID,
    STRUCTURED_TEMPLATE_MIGRATION_ID,
    WORLD_FORM_MIGRATION_ID,
    book_outline_form_to_markdown,
    book_outline_markdown_to_form,
    character_profile_form_defaults,
    character_profile_form_to_markdown,
    world_form_defaults,
    world_form_to_markdown,
)

CHARACTER_STATE_MACHINE_MIGRATION_ID = "character_state_machine_v1"
CHARACTER_STATE_MACHINE_STATIC_ATTRS_MIGRATION_ID = "character_state_machine_static_attrs_v1"
CHAPTER_GENERATION_SNAPSHOT_MIGRATION_ID = "chapter_generation_snapshot_v1"
COMMUNITY_CARD_POSTS_MIGRATION_ID = "20260629_create_community_card_posts"
FTS5_CHAPTERS_MIGRATION_ID = "fts5_chapters_v2"
SYNC_CHANGELOG_MIGRATION_ID = "sync_changelog_v1"
HNSW_VECTORS_MIGRATION_ID = "hnsw_vectors_v1"


class SchemaMixin:
    def initialize(self) -> None:
        self._reset_database_for_current_epoch()
        with self.connection:
            self.connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                outline_text TEXT NOT NULL DEFAULT '',
                outline_data_json TEXT NOT NULL DEFAULT '',
                world_text TEXT NOT NULL DEFAULT '',
                world_data_json TEXT NOT NULL DEFAULT '',
                cover_image_path TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS volumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                outline_text TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                volume_id INTEGER,
                title TEXT NOT NULL,
                outline TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL DEFAULT '',
                ai_probability INTEGER NOT NULL DEFAULT 0,
                ai_probability_level TEXT NOT NULL DEFAULT 'none',
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (volume_id) REFERENCES volumes(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS reference_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                source_path TEXT NOT NULL,
                rights_note TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'book',
                source_url TEXT NOT NULL DEFAULT '',
                source_license TEXT NOT NULL DEFAULT '',
                reusable_level TEXT NOT NULL DEFAULT 'pattern_only',
                attribution_note TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS book_reference_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'style_reference',
                import_mode TEXT NOT NULL DEFAULT 'base_data',
                notes TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, source_id),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES reference_sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS book_reference_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, source_id, segment_index),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES reference_sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS distilled_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                instruction_text TEXT NOT NULL,
                use_cases_text TEXT NOT NULL DEFAULT '',
                risk_note TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES reference_sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS skill_bindings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT NOT NULL,
                scope_id INTEGER NOT NULL,
                skill_id INTEGER NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scope_type, scope_id, skill_id),
                FOREIGN KEY (skill_id) REFERENCES distilled_skills(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                profile_text TEXT NOT NULL DEFAULT '',
                profile_data_json TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                graph_x REAL NOT NULL DEFAULT 0,
                graph_y REAL NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS character_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_character_id INTEGER NOT NULL,
                target_character_id INTEGER NOT NULL,
                relationship_type TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (target_character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS character_state_machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL UNIQUE,
                -- 静态属性（身份基底）
                alias TEXT NOT NULL DEFAULT '',
                age TEXT NOT NULL DEFAULT '',
                gender TEXT NOT NULL DEFAULT '',
                appearance_keywords TEXT NOT NULL DEFAULT '',
                signature_feature TEXT NOT NULL DEFAULT '',
                identity_occupation TEXT NOT NULL DEFAULT '',
                -- 轴1：星座（欲望层）
                desire_text TEXT NOT NULL DEFAULT '',
                desire_origin TEXT NOT NULL DEFAULT '',
                desire_anchor TEXT NOT NULL DEFAULT '',
                desire_extreme TEXT NOT NULL DEFAULT '',
                desire_fear_mirror TEXT NOT NULL DEFAULT '',
                -- 轴2：MBTI（认知层）
                mbti_type TEXT NOT NULL DEFAULT '',
                mbti_i_e TEXT NOT NULL DEFAULT '',
                mbti_n_s TEXT NOT NULL DEFAULT '',
                mbti_t_f TEXT NOT NULL DEFAULT '',
                mbti_j_p TEXT NOT NULL DEFAULT '',
                mbti_strategy TEXT NOT NULL DEFAULT '',
                mbti_advantage TEXT NOT NULL DEFAULT '',
                mbti_blindspot TEXT NOT NULL DEFAULT '',
                -- 轴3：命理（边界层）
                fate_type TEXT NOT NULL DEFAULT '',
                fate_content TEXT NOT NULL DEFAULT '',
                fate_trigger TEXT NOT NULL DEFAULT '',
                fate_target TEXT NOT NULL DEFAULT '',
                fate_limit TEXT NOT NULL DEFAULT '',
                -- 价值观筛选器
                belief_core TEXT NOT NULL DEFAULT '',
                belief_origin TEXT NOT NULL DEFAULT '',
                belief_alignment TEXT NOT NULL DEFAULT '',
                belief_sacrifice TEXT NOT NULL DEFAULT '',
                belief_taboo TEXT NOT NULL DEFAULT '',
                -- 运行态快照
                current_desire_state TEXT NOT NULL DEFAULT 'original',
                current_mbti_state TEXT NOT NULL DEFAULT '',
                current_fate_state TEXT NOT NULL DEFAULT 'dormant',
                current_belief_state TEXT NOT NULL DEFAULT 'stable',
                current_friction TEXT NOT NULL DEFAULT 'none',
                current_dilemma TEXT NOT NULL DEFAULT '',
                total_change_score INTEGER NOT NULL DEFAULT 0,
                last_update_source TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_state_machines_character ON character_state_machines(character_id);

            CREATE TABLE IF NOT EXISTS character_cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                cycle_type TEXT NOT NULL,
                cycle_code TEXT NOT NULL DEFAULT '',
                triggered_desire TEXT NOT NULL DEFAULT '',
                belief_filtered_strategy TEXT NOT NULL DEFAULT '',
                action_taken TEXT NOT NULL DEFAULT '',
                world_feedback TEXT NOT NULL DEFAULT '',
                feedback_intensity TEXT NOT NULL DEFAULT '',
                mbti_change TEXT NOT NULL DEFAULT '',
                star_state TEXT NOT NULL DEFAULT '',
                fate_state TEXT NOT NULL DEFAULT '',
                internal_friction TEXT NOT NULL DEFAULT '',
                change_score INTEGER NOT NULL DEFAULT 0,
                cumulative_score INTEGER NOT NULL DEFAULT 0,
                batch_span TEXT NOT NULL DEFAULT '',
                batch_micro_count INTEGER NOT NULL DEFAULT 0,
                batch_summary TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cycles_character ON character_cycles(character_id, sort_order);
            CREATE INDEX IF NOT EXISTS idx_cycles_type ON character_cycles(character_id, cycle_type);

            CREATE TABLE IF NOT EXISTS character_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                snapshot_no INTEGER NOT NULL DEFAULT 1,
                trigger_type TEXT NOT NULL DEFAULT 'threshold',
                trigger_detail TEXT NOT NULL DEFAULT '',
                related_cycle_id INTEGER,
                desire_state TEXT NOT NULL DEFAULT '',
                mbti_state TEXT NOT NULL DEFAULT '',
                fate_state TEXT NOT NULL DEFAULT '',
                belief_state TEXT NOT NULL DEFAULT '',
                friction_level TEXT NOT NULL DEFAULT '',
                phase_dilemma TEXT NOT NULL DEFAULT '',
                phase_change_summary TEXT NOT NULL DEFAULT '',
                micro_cycle_summary TEXT NOT NULL DEFAULT '',
                total_score_at_snapshot INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (related_cycle_id) REFERENCES character_cycles(id) ON DELETE SET NULL,
                UNIQUE(character_id, snapshot_no)
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_character ON character_snapshots(character_id, snapshot_no);

            CREATE TABLE IF NOT EXISTS chapter_ai_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                source_task_id TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS world_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '设定',
                content_text TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapter_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                outline TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapter_generation_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT 'draft',
                outline TEXT NOT NULL DEFAULT '',
                generated_text TEXT NOT NULL DEFAULT '',
                selected_skills_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'success',
                task_id TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_gen_snapshots_chapter ON chapter_generation_snapshots(chapter_id, created_at);

            CREATE TABLE IF NOT EXISTS chapter_tags (
                chapter_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chapter_id, tag),
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS review_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_id INTEGER,
                scope_type TEXT NOT NULL DEFAULT 'chapter',
                status TEXT NOT NULL DEFAULT 'completed',
                truth_snapshot TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                overall_score INTEGER NOT NULL DEFAULT 0,
                snapshot_id INTEGER,
                revised_content TEXT NOT NULL DEFAULT '',
                revised_outline TEXT NOT NULL DEFAULT '',
                final_verdict TEXT NOT NULL DEFAULT '',
                template_comparison TEXT NOT NULL DEFAULT '',
                risk_notes TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at DATETIME,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
                FOREIGN KEY (snapshot_id) REFERENCES chapter_snapshots(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS review_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'low',
                category TEXT NOT NULL DEFAULT '',
                location_hint TEXT NOT NULL DEFAULT '',
                quote_text TEXT NOT NULL DEFAULT '',
                issue_text TEXT NOT NULL DEFAULT '',
                suggestion_text TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES review_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                scope_type TEXT NOT NULL DEFAULT 'book',
                status TEXT NOT NULL DEFAULT 'created',
                pipeline_version TEXT NOT NULL DEFAULT 'draft_mvp_v1',
                input_hash TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                card_uid TEXT NOT NULL,
                card_type TEXT NOT NULL,
                entity_uid TEXT NOT NULL DEFAULT '',
                card_version INTEGER NOT NULL DEFAULT 1,
                ars_score REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft',
                payload_json TEXT NOT NULL,
                diff_json TEXT NOT NULL DEFAULT '{}',
                applied_table TEXT NOT NULL DEFAULT '',
                applied_id INTEGER,
                applied_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(run_id, card_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                block_uid TEXT NOT NULL,
                chunk_id TEXT NOT NULL DEFAULT '',
                chunk_index INTEGER NOT NULL DEFAULT 0,
                chapter_id INTEGER,
                chapter_ids_json TEXT NOT NULL DEFAULT '[]',
                chapter_refs_json TEXT NOT NULL DEFAULT '[]',
                char_start INTEGER NOT NULL DEFAULT 0,
                char_end INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                structure_hash TEXT NOT NULL DEFAULT '',
                pipeline_version TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                indexed_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                UNIQUE(book_id, run_id, block_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER,
                card_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_uid TEXT NOT NULL DEFAULT '',
                old_value_json TEXT NOT NULL DEFAULT '{}',
                new_value_json TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                actor TEXT NOT NULL DEFAULT 'system',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL,
                FOREIGN KEY (card_id) REFERENCES analysis_cards(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS analysis_apply_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER,
                label TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_volumes_book ON volumes(book_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_chapters_book_volume ON chapters(book_id, volume_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_reference_sources_title ON reference_sources(title);
            CREATE INDEX IF NOT EXISTS idx_book_reference_sources_book ON book_reference_sources(book_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_book_reference_segments_book ON book_reference_segments(book_id, source_id, segment_index);
            CREATE INDEX IF NOT EXISTS idx_skills_source ON distilled_skills(source_id);
            CREATE INDEX IF NOT EXISTS idx_bindings_scope ON skill_bindings(scope_type, scope_id);
            CREATE INDEX IF NOT EXISTS idx_characters_book ON characters(book_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_book ON character_relationships(book_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_source ON character_relationships(source_character_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_target ON character_relationships(target_character_id);
            CREATE INDEX IF NOT EXISTS idx_world_entries_book ON world_entries(book_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_chapter ON chapter_snapshots(chapter_id);
            CREATE INDEX IF NOT EXISTS idx_chapter_tags_tag ON chapter_tags(tag, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_ai_spans_chapter ON chapter_ai_spans(chapter_id, start_offset);
            CREATE INDEX IF NOT EXISTS idx_chapter_events_book ON chapter_events(book_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_chapter_events_chapter ON chapter_events(chapter_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_review_runs_book ON review_runs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_review_runs_chapter ON review_runs(chapter_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_review_findings_run ON review_findings(run_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_book ON analysis_runs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_cards_run ON analysis_cards(run_id, card_type, status);
            CREATE INDEX IF NOT EXISTS idx_analysis_cards_book ON analysis_cards(book_id, card_type, updated_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_run ON analysis_blocks(book_id, run_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_block_uid ON analysis_blocks(book_id, block_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_chapter ON analysis_blocks(book_id, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_hash ON analysis_blocks(book_id, content_hash);
            CREATE INDEX IF NOT EXISTS idx_analysis_audit_logs_book ON analysis_audit_logs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_apply_snapshots_book ON analysis_apply_snapshots(book_id, created_at);

            CREATE TABLE IF NOT EXISTS node_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                background TEXT NOT NULL DEFAULT '#FFFFFF',
                border_color TEXT NOT NULL DEFAULT '#D6DFEA',
                border_width REAL NOT NULL DEFAULT 1.5,
                text_color TEXT NOT NULL DEFAULT '#1F2A36',
                icon_type TEXT NOT NULL DEFAULT 'default',
                is_preset INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS relationship_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#5F7088',
                line_style TEXT NOT NULL DEFAULT 'dotted',
                arrow_type TEXT NOT NULL DEFAULT 'bi-directional',
                is_directed INTEGER NOT NULL DEFAULT 0,
                is_preset INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS character_node_styles (
                character_id INTEGER PRIMARY KEY,
                style_id INTEGER NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (style_id) REFERENCES node_styles(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_node_styles_book ON node_styles(book_id);
            CREATE INDEX IF NOT EXISTS idx_relationship_types_book ON relationship_types(book_id);

            CREATE TABLE IF NOT EXISTS sticky_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#FFF9C4',
                pos_x INTEGER NOT NULL DEFAULT 100,
                pos_y INTEGER NOT NULL DEFAULT 100,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sticky_notes_book ON sticky_notes(book_id);

            CREATE TABLE IF NOT EXISTS community_card_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poster_user_id INTEGER NOT NULL,
                card_type TEXT NOT NULL,
                card_name TEXT NOT NULL,
                intro TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                source_book_id INTEGER,
                source_book_title TEXT,
                source_card_id INTEGER,
                view_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(poster_user_id, source_book_id, source_card_id, card_type)
            );

            CREATE INDEX IF NOT EXISTS idx_community_card_posts_type ON community_card_posts(card_type);
            CREATE INDEX IF NOT EXISTS idx_community_card_posts_created ON community_card_posts(created_at DESC);
            """
        )
        self._migrate_schema()
        self._ensure_column("character_relationships", "relationship_type_id", "INTEGER REFERENCES relationship_types(id) ON DELETE SET NULL")
        self._ensure_column("character_relationships", "description", "TEXT NOT NULL DEFAULT ''")
        self._ensure_legacy_imports_table()
        self._apply_app_migrations()
        self._mark_database_reset_epoch()
        self._normalize_all_volume_orders()
        self._normalize_all_chapter_orders()
        # 迁移/规整调用在 with 块之外执行，会留下未决事务；连接改为线程本地后，
        # 未决事务会一直占住写锁并阻塞其他线程写入，必须显式收尾提交
        # 登记基线版本号：从此 schema 变更均有版本可查（历史建表语句不回溯改写），
        # 未来的迁移按新版本号写入 schema_migrations
        migrations.ensure_schema_version(self.connection, "baseline-2026-09")
        self.connection.commit()

    def _reset_database_for_current_epoch(self) -> None:
        if not self._database_has_user_objects():
            return
        if self._app_migration_applied(DATABASE_RESET_EPOCH_ID):
            return
        if not self._database_requires_epoch_reset():
            return
        self._drop_all_database_objects()
        self._clear_database_reset_caches()

    def _database_has_user_objects(self) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger', 'view')
              AND name NOT LIKE 'sqlite_%'
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def _database_requires_epoch_reset(self) -> bool:
        existing_tables = self._existing_table_names()
        if self._is_current_workspace_database() and "books" in existing_tables:
            book_columns = self._table_column_names("books")
            if not {"outline_data_json", "world_text", "world_data_json", "cover_image_path"}.issubset(book_columns):
                return True
        if "characters" in existing_tables and "profile_data_json" not in self._table_column_names("characters"):
            return True
        return bool("world_entries" in existing_tables and "content_text" not in self._table_column_names("world_entries"))

    def _is_current_workspace_database(self) -> bool:
        try:
            return self.db_path.expanduser().resolve() == (self.data_dir / "novels.db").expanduser().resolve()
        except OSError:
            return False

    def _existing_table_names(self) -> set[str]:
        rows = self.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        return {str(row["name"] or "") for row in rows if str(row["name"] or "")}

    def _table_column_names(self, table_name: str) -> set[str]:
        try:
            rows = self.connection.execute(f"PRAGMA table_info({self._sql_identifier(table_name)})").fetchall()
        except sqlite3.Error:
            return set()
        return {str(row["name"] or "") for row in rows if str(row["name"] or "")}

    def _app_migration_applied(self, migration_id: str) -> bool:
        table = self.connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'app_migrations'
            LIMIT 1
            """
        ).fetchone()
        if table is None:
            return False
        try:
            row = self.connection.execute(
                "SELECT 1 FROM app_migrations WHERE id = ?",
                (migration_id,),
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None

    def _drop_all_database_objects(self) -> None:
        order = {"view": 0, "trigger": 1, "index": 2, "table": 3}
        rows = self.connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger', 'view')
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        for row in sorted(rows, key=lambda item: order.get(str(item["type"]), 99)):
            object_type = str(row["type"] or "").lower()
            object_name = str(row["name"] or "")
            if not object_name:
                continue
            if object_type == "table":
                statement = "DROP TABLE IF EXISTS "
            elif object_type == "index":
                statement = "DROP INDEX IF EXISTS "
            elif object_type == "trigger":
                statement = "DROP TRIGGER IF EXISTS "
            elif object_type == "view":
                statement = "DROP VIEW IF EXISTS "
            else:
                continue
            self.connection.execute(statement + self._sql_identifier(object_name))

    def _clear_database_reset_caches(self) -> None:
        try:
            if self.db_path.expanduser().resolve().parent != self.data_dir.expanduser().resolve():
                return
        except OSError:
            return
        for directory in (self.data_dir / "rag_vectors",):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
        if not self.data_dir.exists():
            return
        for child in self.data_dir.iterdir():
            if child.is_dir() and child.name.isdigit():
                shutil.rmtree(child, ignore_errors=True)

    def _mark_database_reset_epoch(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_migrations (
                id TEXT PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (DATABASE_RESET_EPOCH_ID,),
        )

    def update_character_pinned(self, character_id: int, pinned: bool) -> None:
        self.connection.execute(
            "UPDATE characters SET pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if pinned else 0, character_id),
        )
        self.connection.commit()

    def list_sticky_notes(self, book_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT id, book_id, content, color, pos_x, pos_y, created_at FROM sticky_notes WHERE book_id = ? ORDER BY id ASC",
            (book_id,),
        )
        return list(cursor.fetchall())

    def create_sticky_note(self, book_id: int, content: str = "", color: str = "#FFF9C4", pos_x: int = 100, pos_y: int = 100) -> int:
        cursor = self.connection.execute(
            "INSERT INTO sticky_notes (book_id, content, color, pos_x, pos_y) VALUES (?, ?, ?, ?, ?)",
            (book_id, content, color, pos_x, pos_y),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_sticky_note(self, note_id: int, content: str = "", color: str = "#FFF9C4", pos_x: int | None = None, pos_y: int | None = None) -> None:
        if pos_x is not None and pos_y is not None:
            self.connection.execute(
                "UPDATE sticky_notes SET content = ?, color = ?, pos_x = ?, pos_y = ? WHERE id = ?",
                (content, color, pos_x, pos_y, note_id),
            )
        else:
            self.connection.execute(
                "UPDATE sticky_notes SET content = ?, color = ? WHERE id = ?",
                (content, color, note_id),
            )
        self.connection.commit()

    def delete_sticky_note(self, note_id: int) -> None:
        self.connection.execute("DELETE FROM sticky_notes WHERE id = ?", (note_id,))
        self.connection.commit()

    def _migrate_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS volumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                outline_text TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            )
            """
        )
        self._ensure_column("books", "outline_text", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("books", "outline_data_json", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("books", "world_text", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("books", "world_data_json", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("books", "cover_image_path", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("volumes", "outline_text", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("chapters", "summary_text", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("chapters", "volume_id", "INTEGER")
        self._ensure_column("chapters", "ai_probability", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("chapters", "ai_probability_level", "TEXT NOT NULL DEFAULT 'none'")
        self._ensure_column("chapters", "chapter_type", "TEXT NOT NULL DEFAULT '正文'")
        self._ensure_column("characters", "image_path", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("characters", "profile_data_json", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("characters", "graph_x", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("characters", "graph_y", "REAL NOT NULL DEFAULT 0")
        self._ensure_column("reference_sources", "source_type", "TEXT NOT NULL DEFAULT 'book'")
        self._ensure_column("reference_sources", "source_url", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("reference_sources", "source_license", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("reference_sources", "reusable_level", "TEXT NOT NULL DEFAULT 'pattern_only'")
        self._ensure_column("reference_sources", "attribution_note", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("review_runs", "snapshot_id", "INTEGER")
        self._ensure_column("review_runs", "applied_at", "DATETIME")
        self._ensure_column("review_runs", "template_comparison", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("review_runs", "cross_summary", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("review_findings", "dimension", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("review_findings", "conflict_with", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("review_findings", "is_cross_chapter", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("characters", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("books", "cloud_book_id", "TEXT")
        self._ensure_column("books", "user_id", "INTEGER")
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapters_volume ON chapters(volume_id, sort_order, id)"
        )
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chapter_tags (
                chapter_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chapter_id, tag),
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS book_reference_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'style_reference',
                import_mode TEXT NOT NULL DEFAULT 'base_data',
                notes TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, source_id),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES reference_sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS book_reference_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(book_id, source_id, segment_index),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES reference_sources(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS character_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                source_character_id INTEGER NOT NULL,
                target_character_id INTEGER NOT NULL,
                relationship_type TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (source_character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (target_character_id) REFERENCES characters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapter_ai_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                source_task_id TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chapter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS review_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                chapter_id INTEGER,
                scope_type TEXT NOT NULL DEFAULT 'chapter',
                status TEXT NOT NULL DEFAULT 'completed',
                truth_snapshot TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                overall_score INTEGER NOT NULL DEFAULT 0,
                snapshot_id INTEGER,
                revised_content TEXT NOT NULL DEFAULT '',
                revised_outline TEXT NOT NULL DEFAULT '',
                final_verdict TEXT NOT NULL DEFAULT '',
                template_comparison TEXT NOT NULL DEFAULT '',
                risk_notes TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at DATETIME,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE,
                FOREIGN KEY (snapshot_id) REFERENCES chapter_snapshots(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS review_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                agent TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'low',
                category TEXT NOT NULL DEFAULT '',
                location_hint TEXT NOT NULL DEFAULT '',
                quote_text TEXT NOT NULL DEFAULT '',
                issue_text TEXT NOT NULL DEFAULT '',
                suggestion_text TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES review_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                scope_type TEXT NOT NULL DEFAULT 'book',
                status TEXT NOT NULL DEFAULT 'created',
                pipeline_version TEXT NOT NULL DEFAULT 'draft_mvp_v1',
                input_hash TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                card_uid TEXT NOT NULL,
                card_type TEXT NOT NULL,
                entity_uid TEXT NOT NULL DEFAULT '',
                card_version INTEGER NOT NULL DEFAULT 1,
                ars_score REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'draft',
                payload_json TEXT NOT NULL,
                diff_json TEXT NOT NULL DEFAULT '{}',
                applied_table TEXT NOT NULL DEFAULT '',
                applied_id INTEGER,
                applied_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(run_id, card_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                block_uid TEXT NOT NULL,
                chunk_id TEXT NOT NULL DEFAULT '',
                chunk_index INTEGER NOT NULL DEFAULT 0,
                chapter_id INTEGER,
                chapter_ids_json TEXT NOT NULL DEFAULT '[]',
                chapter_refs_json TEXT NOT NULL DEFAULT '[]',
                char_start INTEGER NOT NULL DEFAULT 0,
                char_end INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                structure_hash TEXT NOT NULL DEFAULT '',
                pipeline_version TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                indexed_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                UNIQUE(book_id, run_id, block_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER,
                card_id INTEGER,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_uid TEXT NOT NULL DEFAULT '',
                old_value_json TEXT NOT NULL DEFAULT '{}',
                new_value_json TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                actor TEXT NOT NULL DEFAULT 'system',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL,
                FOREIGN KEY (card_id) REFERENCES analysis_cards(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS analysis_apply_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER,
                label TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_relationships_book ON character_relationships(book_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_source ON character_relationships(source_character_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_target ON character_relationships(target_character_id);
            CREATE INDEX IF NOT EXISTS idx_book_reference_sources_book ON book_reference_sources(book_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_book_reference_segments_book ON book_reference_segments(book_id, source_id, segment_index);
            CREATE INDEX IF NOT EXISTS idx_ai_spans_chapter ON chapter_ai_spans(chapter_id, start_offset);
            CREATE INDEX IF NOT EXISTS idx_chapter_tags_tag ON chapter_tags(tag, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_chapter_events_book ON chapter_events(book_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_chapter_events_chapter ON chapter_events(chapter_id, sort_order, id);
            CREATE INDEX IF NOT EXISTS idx_review_runs_book ON review_runs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_review_runs_chapter ON review_runs(chapter_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_review_findings_run ON review_findings(run_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_book ON analysis_runs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_cards_run ON analysis_cards(run_id, card_type, status);
            CREATE INDEX IF NOT EXISTS idx_analysis_cards_book ON analysis_cards(book_id, card_type, updated_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_run ON analysis_blocks(book_id, run_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_block_uid ON analysis_blocks(book_id, block_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_chapter ON analysis_blocks(book_id, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_hash ON analysis_blocks(book_id, content_hash);
            CREATE INDEX IF NOT EXISTS idx_analysis_audit_logs_book ON analysis_audit_logs(book_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_analysis_apply_snapshots_book ON analysis_apply_snapshots(book_id, created_at);

            CREATE TABLE IF NOT EXISTS name_shortcuts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                key_seq TEXT NOT NULL DEFAULT '',
                character_name TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_name_shortcuts_book ON name_shortcuts(book_id);
            """
        )

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> None:
        # 委托共享迁移工具：用 PRAGMA table_info 判断列存在性，
        # 不再依赖 except OperationalError + "duplicate column name" 字符串匹配
        migrations.ensure_column(self.connection, table_name, column_name, definition)

    def _apply_analysis_v3_foundation_migration(self) -> None:
        self._ensure_column("analysis_blocks", "structure_hash", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("analysis_blocks", "pipeline_version", "TEXT NOT NULL DEFAULT ''")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS analysis_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                entity_uid TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                canonical_name TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                source_rule TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(book_id, run_id, entity_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_entity_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                mention_uid TEXT NOT NULL,
                entity_uid TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                normalized_text TEXT NOT NULL DEFAULT '',
                quote_text TEXT NOT NULL DEFAULT '',
                chapter_id INTEGER,
                block_uid TEXT NOT NULL DEFAULT '',
                char_start INTEGER NOT NULL DEFAULT 0,
                char_end INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                UNIQUE(book_id, run_id, mention_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_entity_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                entity_uid TEXT NOT NULL,
                alias TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system',
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(book_id, run_id, entity_uid, alias)
            );

            CREATE TABLE IF NOT EXISTS analysis_entity_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                source_entity_uid TEXT NOT NULL,
                target_entity_uid TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_entity_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                entity_uid TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                action TEXT NOT NULL DEFAULT '',
                old_value_json TEXT NOT NULL DEFAULT '{}',
                new_value_json TEXT NOT NULL DEFAULT '{}',
                actor TEXT NOT NULL DEFAULT 'system',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                fact_uid TEXT NOT NULL,
                subject_entity_uid TEXT NOT NULL DEFAULT '',
                fact_type TEXT NOT NULL DEFAULT '',
                value_json TEXT NOT NULL DEFAULT '{}',
                quote_text TEXT NOT NULL DEFAULT '',
                chapter_id INTEGER,
                block_uid TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                memory_scope TEXT NOT NULL DEFAULT '',
                memory_importance TEXT NOT NULL DEFAULT '',
                memory_type TEXT NOT NULL DEFAULT '',
                importance_score REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                UNIQUE(book_id, run_id, fact_uid)
            );

            CREATE TABLE IF NOT EXISTS foreshadows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'medium',
                source TEXT NOT NULL DEFAULT 'manual',
                setup_chapter_id INTEGER,
                payoff_chapter_id INTEGER,
                resolution_note TEXT NOT NULL DEFAULT '',
                fact_uid TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (setup_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL,
                FOREIGN KEY (payoff_chapter_id) REFERENCES chapters(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_foreshadows_book_id ON foreshadows(book_id);
            CREATE INDEX IF NOT EXISTS idx_foreshadows_status ON foreshadows(book_id, status);
            CREATE INDEX IF NOT EXISTS idx_foreshadows_fact_uid ON foreshadows(fact_uid);

            CREATE TABLE IF NOT EXISTS analysis_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                event_uid TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                error_text TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(book_id, run_id, event_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_card_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                card_uid TEXT NOT NULL,
                dependency_type TEXT NOT NULL DEFAULT '',
                dependency_uid TEXT NOT NULL DEFAULT '',
                dependency_hash TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_backtrack_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                task_uid TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT '',
                target_uid TEXT NOT NULL DEFAULT '',
                impact_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                error_text TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(book_id, run_id, task_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_probe_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                probe_uid TEXT NOT NULL,
                probe_type TEXT NOT NULL DEFAULT '',
                subject_entity_uid TEXT NOT NULL DEFAULT '',
                plan_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
                UNIQUE(book_id, run_id, probe_uid)
            );

            CREATE TABLE IF NOT EXISTS analysis_probe_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                probe_uid TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                consistency TEXT NOT NULL DEFAULT 'unknown',
                confidence REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'candidate',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS analysis_llm_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                stage TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                schema_version TEXT NOT NULL DEFAULT '',
                input_hash TEXT NOT NULL DEFAULT '',
                output_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_structure_hash ON analysis_blocks(book_id, structure_hash);
            CREATE INDEX IF NOT EXISTS idx_analysis_blocks_pipeline ON analysis_blocks(book_id, pipeline_version);
            CREATE INDEX IF NOT EXISTS idx_analysis_entities_uid ON analysis_entities(book_id, entity_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_entities_run ON analysis_entities(book_id, run_id, status);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_mentions_run_block ON analysis_entity_mentions(book_id, run_id, block_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_mentions_chapter ON analysis_entity_mentions(book_id, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_aliases_uid ON analysis_entity_aliases(book_id, entity_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_edges_source ON analysis_entity_edges(book_id, source_entity_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_edges_target ON analysis_entity_edges(book_id, target_entity_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_entity_versions_uid ON analysis_entity_versions(book_id, entity_uid, version);
            CREATE INDEX IF NOT EXISTS idx_analysis_facts_subject ON analysis_facts(book_id, subject_entity_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_facts_run_block ON analysis_facts(book_id, run_id, block_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_facts_chapter ON analysis_facts(book_id, chapter_id);
            CREATE INDEX IF NOT EXISTS idx_analysis_events_queue ON analysis_events(book_id, status, priority);
            CREATE INDEX IF NOT EXISTS idx_analysis_card_dependencies_card ON analysis_card_dependencies(book_id, run_id, card_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_card_dependencies_uid ON analysis_card_dependencies(book_id, dependency_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_backtrack_queue ON analysis_backtrack_tasks(book_id, status, priority);
            CREATE INDEX IF NOT EXISTS idx_analysis_probe_plans_queue ON analysis_probe_plans(book_id, status, priority);
            CREATE INDEX IF NOT EXISTS idx_analysis_probe_results_probe ON analysis_probe_results(book_id, run_id, probe_uid);
            CREATE INDEX IF NOT EXISTS idx_analysis_llm_cache_stage ON analysis_llm_cache(stage, input_hash);
            """
        )
        self._ensure_column("analysis_entities", "source_rule", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("analysis_entity_mentions", "source_rule", "TEXT NOT NULL DEFAULT ''")
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (ANALYSIS_V3_FOUNDATION_MIGRATION_ID,),
        )

    def _apply_character_state_machine_migration(self) -> None:
        """建表 + 为现有 characters 创建空状态机行。"""
        if self._app_migration_applied(CHARACTER_STATE_MACHINE_MIGRATION_ID):
            return
        # 建表已在 initialize 的 executescript 中完成（CREATE TABLE IF NOT EXISTS 保证幂等）
        # 为现有 characters 创建空状态机行
        self.connection.execute(
            """
            INSERT OR IGNORE INTO character_state_machines (character_id)
            SELECT id FROM characters
            WHERE id NOT IN (SELECT character_id FROM character_state_machines)
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (CHARACTER_STATE_MACHINE_MIGRATION_ID,),
        )

    def _apply_character_state_machine_static_attrs_migration(self) -> None:
        """为 character_state_machines 表新增 6 个静态属性字段（幂等迁移）。"""
        if self._app_migration_applied(CHARACTER_STATE_MACHINE_STATIC_ATTRS_MIGRATION_ID):
            return
        static_attrs_columns = [
            ("alias", "TEXT NOT NULL DEFAULT ''"),
            ("age", "TEXT NOT NULL DEFAULT ''"),
            ("gender", "TEXT NOT NULL DEFAULT ''"),
            ("appearance_keywords", "TEXT NOT NULL DEFAULT ''"),
            ("signature_feature", "TEXT NOT NULL DEFAULT ''"),
            ("identity_occupation", "TEXT NOT NULL DEFAULT ''"),
        ]
        for column_name, definition in static_attrs_columns:
            # 列已存在则跳过（幂等，由共享迁移工具用 PRAGMA table_info 判断）
            self._ensure_column("character_state_machines", column_name, definition)
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (CHARACTER_STATE_MACHINE_STATIC_ATTRS_MIGRATION_ID,),
        )

    def _apply_chapter_generation_snapshot_migration(self) -> None:
        """建表（IF NOT EXISTS 保证幂等）。

        建表 DDL 已在 initialize 的 executescript 中完成（CREATE TABLE IF NOT EXISTS
        保证幂等），此处仅标记迁移完成。"""
        if self._app_migration_applied(CHAPTER_GENERATION_SNAPSHOT_MIGRATION_ID):
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (CHAPTER_GENERATION_SNAPSHOT_MIGRATION_ID,),
        )

    def _apply_fts5_chapters_migration(self) -> None:
        """创建 chapters_fts FTS5 虚拟表与触发器，并回填已有章节。

        - 使用 external content 表模式 (content=chapters, content_rowid=id)
        - tokenize=unicode61：默认对 CJK 不分词，需配合 cjk_unigram 函数预处理
        - 三个触发器在写入时调用 cjk_unigram() 把 CJK 字符单字分隔后存入 FTS5
          这样 unicode61 按空格切分，每个中文字符成为独立 token，支持任意子串搜索
        - 已有数据通过 `INSERT INTO chapters_fts(rowid, title, content) SELECT id, cjk_unigram(title), cjk_unigram(content) ...` 回填

        v2 变更：相比 v1（直接存原始内容导致中文搜不到），v2 在触发器与回填中
        调用 cjk_unigram 预处理。已应用 v1 的数据库会重建 FTS5 索引。

        若 SQLite 编译时未启用 FTS5，则跳过创建并记日志，search_book 自动降级为
        Python 层 str.find 扫描。
        """
        if self._app_migration_applied(FTS5_CHAPTERS_MIGRATION_ID):
            return
        try:
            # 1. 清理 v1 残留（触发器 + FTS5 表），v2 需用 cjk_unigram 重建
            self.connection.executescript(
                """
                DROP TRIGGER IF EXISTS chapters_fts_ai;
                DROP TRIGGER IF EXISTS chapters_fts_ad;
                DROP TRIGGER IF EXISTS chapters_fts_au;
                DROP TABLE IF EXISTS chapters_fts;
                """
            )
            # 2. 创建 FTS5 外部 content 虚拟表 + 触发器（调用 cjk_unigram）
            self.connection.executescript(
                """
                CREATE VIRTUAL TABLE chapters_fts USING fts5(
                    title,
                    content,
                    content='chapters',
                    content_rowid='id',
                    tokenize='unicode61'
                );

                -- INSERT 触发器：新增章节时同步到 FTS5（CJK 字符经 cjk_unigram 单字分隔）
                CREATE TRIGGER chapters_fts_ai AFTER INSERT ON chapters BEGIN
                    INSERT INTO chapters_fts(rowid, title, content)
                    VALUES (new.id, cjk_unigram(new.title), cjk_unigram(new.content));
                END;

                -- DELETE 触发器：删除章节时从 FTS5 移除（delete 命令需匹配原插入值）
                CREATE TRIGGER chapters_fts_ad AFTER DELETE ON chapters BEGIN
                    INSERT INTO chapters_fts(chapters_fts, rowid, title, content)
                    VALUES ('delete', old.id, cjk_unigram(old.title), cjk_unigram(old.content));
                END;

                -- UPDATE 触发器：章节标题或正文变化时重建对应行
                CREATE TRIGGER chapters_fts_au AFTER UPDATE ON chapters BEGIN
                    INSERT INTO chapters_fts(chapters_fts, rowid, title, content)
                    VALUES ('delete', old.id, cjk_unigram(old.title), cjk_unigram(old.content));
                    INSERT INTO chapters_fts(rowid, title, content)
                    VALUES (new.id, cjk_unigram(new.title), cjk_unigram(new.content));
                END;
                """
            )
            # 3. 回填已有数据（同样经 cjk_unigram 处理）
            self.connection.execute(
                """
                INSERT INTO chapters_fts(rowid, title, content)
                SELECT id, cjk_unigram(title), cjk_unigram(content) FROM chapters
                """
            )
        except sqlite3.OperationalError as exc:
            # FTS5 不可用：跳过迁移，保持 search_book 旧路径可用
            # 不写入 migration id，下次启动会重试
            if "fts5" not in str(exc).lower():
                raise
            return
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (FTS5_CHAPTERS_MIGRATION_ID,),
        )

    def _apply_sync_changelog_migration(self) -> None:
        """创建 sync_changelog 表用于追踪离线变更。

        schema 设计与 hybrid-database-architecture spec Task 6 对齐：
        - table_name: 变更涉及的表名
        - row_id: 变更行的主键 ID（多列主键时存 JSON 字符串）
        - operation: 'insert' | 'update' | 'delete'
        - timestamp: 变更发生的时间（UTC ISO 字符串）
        - synced: 0=待同步，1=已同步
        - payload_json: 行快照（用于 delete 后云端删除 / insert 后云端重建）
        """
        if self._app_migration_applied(SYNC_CHANGELOG_MIGRATION_ID):
            return
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sync_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name TEXT NOT NULL,
                row_id TEXT NOT NULL,
                operation TEXT NOT NULL CHECK(operation IN ('insert','update','delete')),
                timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                synced INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sync_changelog_unsynced
                ON sync_changelog(synced, timestamp);
            CREATE INDEX IF NOT EXISTS idx_sync_changelog_table_row
                ON sync_changelog(table_name, row_id);
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (SYNC_CHANGELOG_MIGRATION_ID,),
        )

    def _apply_hnsw_vectors_migration(self) -> None:
        """创建 vectors 持久化表，供 HNSWStore 存储向量数据。

        schema 设计与 hybrid-database-architecture spec Task 2.8 对齐：
        - collection: collection 名（如 'book_1', 'analysis_blocks_1'）
        - point_id: 点 ID（支持 int 和 str，统一存 TEXT）
        - vector_blob: 向量二进制（float32 数组的 bytes，由 numpy.tobytes() 产出）
        - payload_json: 点的元数据 JSON
        - updated_at: 更新时间戳（用于增量同步与排序）

        原方案 spec 写的是 hnswlib，实际改用 faiss-cpu（Python 3.13 + Windows
        无 hnswlib 预编译 wheel，faiss-cpu 的 IndexHNSWFlat 算法等价且性能相当）。
        """
        if self._app_migration_applied(HNSW_VECTORS_MIGRATION_ID):
            return
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                point_id TEXT NOT NULL,
                vector_blob BLOB NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                dim INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(collection, point_id)
            );

            CREATE INDEX IF NOT EXISTS idx_vectors_collection
                ON vectors(collection);
            CREATE INDEX IF NOT EXISTS idx_vectors_collection_point
                ON vectors(collection, point_id);
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO app_migrations (id) VALUES (?)",
            (HNSW_VECTORS_MIGRATION_ID,),
        )

    def _apply_app_migrations(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_migrations (
                id TEXT PRIMARY KEY,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._apply_analysis_v3_foundation_migration()
        structured_applied = self.connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (STRUCTURED_TEMPLATE_MIGRATION_ID,),
        ).fetchone()
        if not structured_applied:
            characters = self.connection.execute("SELECT id, name, role FROM characters").fetchall()
            for character in characters:
                name = str(character["name"] or "")
                role = str(character["role"] or "")
                profile_data = character_profile_form_defaults(name, role)
                profile_text = character_profile_form_to_markdown(profile_data, name, role)
                self.connection.execute(
                    "UPDATE characters SET profile_text = ?, profile_data_json = ? WHERE id = ?",
                    (profile_text, self._character_profile_data_to_json(profile_data, name, role), int(character["id"])),
                )

            self.connection.execute(
                "INSERT INTO app_migrations (id) VALUES (?)",
                (STRUCTURED_TEMPLATE_MIGRATION_ID,),
            )

        outline_form_applied = self.connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (BOOK_OUTLINE_FORM_MIGRATION_ID,),
        ).fetchone()
        if not outline_form_applied:
            books = self.connection.execute("SELECT id, title, outline_text, outline_data_json FROM books").fetchall()
            for book in books:
                title = str(book["title"] or "")
                volume_specs = self._book_outline_volume_specs(int(book["id"]))
                data = self._book_outline_json_to_data(str(book["outline_data_json"] or ""), title, volume_specs)
                if not data:
                    data = book_outline_markdown_to_form(str(book["outline_text"] or ""), title, volume_specs)
                markdown = book_outline_form_to_markdown(data, title, volume_specs)
                self.connection.execute(
                    "UPDATE books SET outline_text = ?, outline_data_json = ? WHERE id = ?",
                    (markdown, self._book_outline_data_to_json(data, title, volume_specs), int(book["id"])),
                )

            self.connection.execute(
                "INSERT INTO app_migrations (id) VALUES (?)",
                (BOOK_OUTLINE_FORM_MIGRATION_ID,),
            )

        world_form_applied = self.connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (WORLD_FORM_MIGRATION_ID,),
        ).fetchone()
        if not world_form_applied:
            books = self.connection.execute("SELECT id FROM books").fetchall()
            for book in books:
                book_id = int(book["id"])
                world_data = world_form_defaults()
                self.connection.execute(
                    "UPDATE books SET world_text = ?, world_data_json = ? WHERE id = ?",
                    (world_form_to_markdown(world_data), self._world_form_data_to_json(world_data), book_id),
                )
                self.connection.execute("DELETE FROM world_entries WHERE book_id = ?", (book_id,))
            self.connection.execute(
                "INSERT INTO app_migrations (id) VALUES (?)",
                (WORLD_FORM_MIGRATION_ID,),
            )

        character_form_applied = self.connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (CHARACTER_PROFILE_FORM_MIGRATION_ID,),
        ).fetchone()
        if not character_form_applied:
            characters = self.connection.execute("SELECT id, name, role FROM characters").fetchall()
            for character in characters:
                name = str(character["name"] or "")
                role = str(character["role"] or "")
                profile_data = character_profile_form_defaults(name, role)
                profile_text = character_profile_form_to_markdown(profile_data, name, role)
                self.connection.execute(
                    "UPDATE characters SET profile_text = ?, profile_data_json = ? WHERE id = ?",
                    (profile_text, self._character_profile_data_to_json(profile_data, name, role), int(character["id"])),
                )
            self.connection.execute(
                "INSERT INTO app_migrations (id) VALUES (?)",
                (CHARACTER_PROFILE_FORM_MIGRATION_ID,),
            )

        self._apply_character_state_machine_migration()
        self._apply_character_state_machine_static_attrs_migration()
        self._apply_chapter_generation_snapshot_migration()
        self._apply_fts5_chapters_migration()
        self._apply_sync_changelog_migration()
        self._apply_hnsw_vectors_migration()

        community_card_posts_applied = self.connection.execute(
            "SELECT 1 FROM app_migrations WHERE id = ?",
            (COMMUNITY_CARD_POSTS_MIGRATION_ID,),
        ).fetchone()
        if not community_card_posts_applied:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS community_card_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poster_user_id INTEGER NOT NULL,
                    card_type TEXT NOT NULL,
                    card_name TEXT NOT NULL,
                    intro TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    source_book_id INTEGER,
                    source_book_title TEXT,
                    source_card_id INTEGER,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(poster_user_id, source_book_id, source_card_id, card_type)
                );

                CREATE INDEX IF NOT EXISTS idx_community_card_posts_type ON community_card_posts(card_type);
                CREATE INDEX IF NOT EXISTS idx_community_card_posts_created ON community_card_posts(created_at DESC);
                """
            )
            self.connection.execute(
                "INSERT INTO app_migrations (id) VALUES (?)",
                (COMMUNITY_CARD_POSTS_MIGRATION_ID,),
            )

    def _normalize_all_volume_orders(self) -> None:
        books = self.connection.execute("SELECT id FROM books").fetchall()
        for row in books:
            self._normalize_volume_order(int(row["id"]))

    def _normalize_volume_order(self, book_id: int) -> None:
        rows = self.connection.execute(
            """
            SELECT id
            FROM volumes
            WHERE book_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (book_id,),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            self.connection.execute(
                "UPDATE volumes SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (index, int(row["id"])),
            )

    def _normalize_all_chapter_orders(self) -> None:
        rows = self.connection.execute(
            """
            SELECT DISTINCT book_id, volume_id
            FROM chapters
            ORDER BY book_id ASC, volume_id ASC
            """
        ).fetchall()
        for row in rows:
            self._normalize_chapter_order(int(row["book_id"]), row["volume_id"])

    def _normalize_chapter_order(self, book_id: int, volume_id: int | None) -> None:
        clause, params = self._build_volume_clause(volume_id)
        rows = self.connection.execute(
            f"""
            SELECT id
            FROM chapters
            WHERE book_id = ? AND {clause}
            ORDER BY sort_order ASC, id ASC
            """,
            (book_id, *params),
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            self.connection.execute(
                "UPDATE chapters SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (index, int(row["id"])),
            )

    def _build_volume_clause(self, volume_id: int | None, column_name: str = "volume_id") -> tuple[str, tuple[Any, ...]]:
        allowed_columns = {"volume_id", "book_id", "sort_order"}
        if column_name not in allowed_columns:
            raise ValueError(f"Invalid column name for volume clause: {column_name}")
        if volume_id is None:
            return f"{column_name} IS NULL", ()
        return f"{column_name} = ?", (volume_id,)
