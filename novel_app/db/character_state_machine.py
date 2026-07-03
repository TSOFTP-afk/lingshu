from __future__ import annotations

from novel_app.db.common import *


# 状态机主表可写入字段白名单（不含 id/character_id/created_at/updated_at）
STATE_MACHINE_FIELD_IDS: set[str] = {
    # 静态属性
    "alias", "age", "gender", "appearance_keywords",
    "signature_feature", "identity_occupation",
    # 轴1：星座（欲望层）
    "desire_text", "desire_origin", "desire_anchor", "desire_extreme", "desire_fear_mirror",
    # 轴2：MBTI（认知层）
    "mbti_type", "mbti_i_e", "mbti_n_s", "mbti_t_f", "mbti_j_p",
    "mbti_strategy", "mbti_advantage", "mbti_blindspot",
    # 轴3：命理（边界层）
    "fate_type", "fate_content", "fate_trigger", "fate_target", "fate_limit",
    # 价值观筛选器
    "belief_core", "belief_origin", "belief_alignment", "belief_sacrifice", "belief_taboo",
    # 运行态快照
    "current_desire_state", "current_mbti_state", "current_fate_state",
    "current_belief_state", "current_friction", "current_dilemma",
    "total_change_score", "last_update_source",
}

# 运行态快照字段子集
RUNNING_SNAPSHOT_FIELDS: set[str] = {
    "current_desire_state", "current_mbti_state", "current_fate_state",
    "current_belief_state", "current_friction", "current_dilemma", "last_update_source",
}

# (cycle_type, intensity) → 增值分值
_CYCLE_SCORE_MAP: dict[tuple[str, str], int] = {
    ("micro", ""): 1,
    ("main", "light"): 3,
    ("main", "medium"): 5,
    ("main", "heavy"): 8,
    ("heavy", "existential"): 10,
}

# cycle_type → cycle_code 前缀（main=M, heavy=H, micro 批次=μ）
_CYCLE_CODE_PREFIX: dict[str, str] = {
    "micro": "μ",
    "main": "M",
    "heavy": "H",
}


def _resolve_cycle_score(cycle_type: str, intensity: str) -> int:
    """根据 (cycle_type, intensity) 计算本次循环的增值分值。"""
    key = (cycle_type, (intensity or "").strip())
    if key in _CYCLE_SCORE_MAP:
        return _CYCLE_SCORE_MAP[key]
    # 兜底：micro=1，main 未匹配 intensity 视为 medium=5，heavy 未匹配视为 existential=10
    if cycle_type == "micro":
        return 1
    if cycle_type == "main":
        return _CYCLE_SCORE_MAP[("main", "medium")]
    if cycle_type == "heavy":
        return _CYCLE_SCORE_MAP[("heavy", "existential")]
    return 1


class CharacterStateMachineMixin:
    # ------------------------------------------------------------------
    # 状态机主表 CRUD
    # ------------------------------------------------------------------

    def get_state_machine(self, character_id: int) -> sqlite3.Row | None:
        """读取状态机主表（含三轴+价值观+运行态快照+总变化经验值）。"""
        cursor = self.connection.execute(
            """
            SELECT *
            FROM character_state_machines
            WHERE character_id = ?
            """,
            (character_id,),
        )
        return cursor.fetchone()

    def create_state_machine(self, character_id: int, data: dict) -> int:
        """创建状态机行。data 中的键必须是 STATE_MACHINE_FIELD_IDS 白名单内的字段。
        未提供的字段使用数据库默认值。返回新行 id。
        使用 INSERT OR IGNORE 保证幂等（character_id UNIQUE）。"""
        filtered = {
            key: value for key, value in (data or {}).items()
            if key in STATE_MACHINE_FIELD_IDS
        }
        if not filtered:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO character_state_machines (character_id) VALUES (?)",
                (character_id,),
            )
            self.connection.commit()
            return int(cursor.lastrowid or 0)

        columns = ["character_id"] + list(filtered.keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(self._sql_identifier(col) for col in columns)
        params = [character_id, *filtered.values()]
        cursor = self.connection.execute(
            f"INSERT OR IGNORE INTO character_state_machines ({column_sql}) VALUES ({placeholders})",
            tuple(params),
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def update_state_machine(self, character_id: int, data: dict) -> None:
        """更新状态机字段。仅更新 data 中提供的、且在白名单内的字段。
        同时更新 updated_at = CURRENT_TIMESTAMP。"""
        filtered = {
            key: value for key, value in (data or {}).items()
            if key in STATE_MACHINE_FIELD_IDS
        }
        if not filtered:
            return
        set_clause = ", ".join(
            f"{self._sql_identifier(col)} = ?" for col in filtered.keys()
        )
        params = [*filtered.values(), character_id]
        self.connection.execute(
            f"""
            UPDATE character_state_machines
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE character_id = ?
            """,
            tuple(params),
        )
        self.connection.commit()

    def update_running_snapshot(self, character_id: int, snapshot: dict) -> None:
        """仅更新运行态快照相关字段，并更新 updated_at。"""
        filtered = {
            key: value for key, value in (snapshot or {}).items()
            if key in RUNNING_SNAPSHOT_FIELDS
        }
        if not filtered:
            return
        set_clause = ", ".join(
            f"{self._sql_identifier(col)} = ?" for col in filtered.keys()
        )
        params = [*filtered.values(), character_id]
        self.connection.execute(
            f"""
            UPDATE character_state_machines
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE character_id = ?
            """,
            tuple(params),
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # 循环日志
    # ------------------------------------------------------------------

    def list_cycles(self, character_id: int, cycle_type: str | None = None) -> list:
        """列出循环日志，按 sort_order 升序。cycle_type 可选过滤。"""
        if cycle_type:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM character_cycles
                WHERE character_id = ? AND cycle_type = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (character_id, cycle_type),
            )
        else:
            cursor = self.connection.execute(
                """
                SELECT *
                FROM character_cycles
                WHERE character_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (character_id,),
            )
        return list(cursor.fetchall())

    def create_cycle(self, character_id: int, cycle_data: dict) -> dict:
        """创建循环日志并自动处理增值+快照。核心方法。

        多表写入（cycles + state_machines + snapshots），不在方法内自行 commit，
        由调用方的 transaction() 统一管理。
        """
        data = dict(cycle_data or {})
        cycle_type = str(data.get("cycle_type", "") or "").strip()
        intensity = str(data.get("intensity", "") or "").strip()

        # 1. 计算本次增值
        change_score = _resolve_cycle_score(cycle_type, intensity)

        # 2. 获取当前累计增值
        sm_row = self.get_state_machine(character_id)
        old_total = int(sm_row["total_change_score"]) if sm_row else 0

        # 3. 计算新累计
        new_cumulative = old_total + change_score

        # 4. 自动生成 cycle_code（如 M#1, N#1, H#1）
        cycle_code = str(data.get("cycle_code", "") or "").strip()
        if not cycle_code:
            prefix = _CYCLE_CODE_PREFIX.get(cycle_type, "X")
            existing_count = self.connection.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM character_cycles
                WHERE character_id = ? AND cycle_type = ?
                """,
                (character_id, cycle_type),
            ).fetchone()
            seq = int(existing_count["cnt"]) + 1 if existing_count else 1
            cycle_code = f"{prefix}#{seq}"

        # 5. 计算 sort_order = 该 character 已有循环总数 + 1
        total_row = self.connection.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM character_cycles
            WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        sort_order = int(total_row["cnt"]) + 1 if total_row else 1

        # 6. INSERT character_cycles 行（含 change_score, cumulative_score）
        cursor = self.connection.execute(
            """
            INSERT INTO character_cycles (
                character_id, cycle_type, cycle_code,
                triggered_desire, belief_filtered_strategy, action_taken, world_feedback,
                feedback_intensity, mbti_change, star_state, fate_state, internal_friction,
                change_score, cumulative_score, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character_id, cycle_type, cycle_code,
                str(data.get("triggered_desire", "") or ""),
                str(data.get("belief_filtered_strategy", "") or ""),
                str(data.get("action_taken", "") or ""),
                str(data.get("world_feedback", "") or ""),
                str(data.get("feedback_intensity", intensity) or ""),
                str(data.get("mbti_change", "") or ""),
                str(data.get("star_state", "") or ""),
                str(data.get("fate_state", "") or ""),
                str(data.get("internal_friction", "") or ""),
                change_score, new_cumulative, sort_order,
            ),
        )
        cycle_id = int(cursor.lastrowid or 0)

        # 7. 更新累计增值（不在此处 commit，由 transaction 管理）
        new_total, crossed_threshold = self._add_change_score_no_commit(
            character_id, change_score
        )

        # 8. 更新运行态快照
        snapshot_update: dict[str, Any] = {"last_update_source": cycle_code}
        mbti_change = str(data.get("mbti_change", "") or "")
        if mbti_change:
            snapshot_update["current_mbti_state"] = mbti_change
        star_state = str(data.get("star_state", "") or "")
        if star_state:
            snapshot_update["current_desire_state"] = star_state
        fate_state = str(data.get("fate_state", "") or "")
        if fate_state:
            snapshot_update["current_fate_state"] = fate_state
        internal_friction = str(data.get("internal_friction", "") or "")
        if internal_friction:
            snapshot_update["current_friction"] = internal_friction
        if snapshot_update:
            self._update_running_snapshot_no_commit(character_id, snapshot_update)

        # 9. 判断是否触发存档
        snapshot_created = False
        snapshot_id = None
        trigger_snapshot = False
        trigger_type = ""
        if cycle_type == "heavy":
            trigger_snapshot = True
            trigger_type = "heavy_cycle"
        elif cycle_type == "micro":
            # 微循环不逐条存档（以批次形式记录）
            trigger_snapshot = False
        else:
            # main 循环：跨 10 倍门槛时存档
            if crossed_threshold:
                trigger_snapshot = True
                trigger_type = "threshold"

        # 10. 若触发存档，调用 create_snapshot（不在此处 commit）
        if trigger_snapshot:
            snapshot_id = self._create_snapshot_no_commit(
                character_id,
                trigger_type=trigger_type,
                trigger_detail=cycle_code,
                related_cycle_id=cycle_id,
            )
            snapshot_created = True

        # 11. 返回结果
        return {
            "cycle_id": cycle_id,
            "cumulative_score": new_total,
            "snapshot_created": snapshot_created,
            "snapshot_id": snapshot_id,
        }

    def create_micro_batch(self, character_id: int, batch_data: dict) -> int:
        """创建微循环批次日志（batch_span/batch_micro_count/batch_summary）。
        微循环不逐条记录，以批次形式记录。"""
        data = dict(batch_data or {})
        change_score = _resolve_cycle_score("micro", "")

        old_row = self.get_state_machine(character_id)
        old_total = int(old_row["total_change_score"]) if old_row else 0
        new_cumulative = old_total + change_score

        existing_count = self.connection.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM character_cycles
            WHERE character_id = ? AND cycle_type = 'micro'
            """,
            (character_id,),
        ).fetchone()
        seq = int(existing_count["cnt"]) + 1 if existing_count else 1
        cycle_code = str(data.get("cycle_code", "") or f"μ#{seq}")

        total_row = self.connection.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM character_cycles
            WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        sort_order = int(total_row["cnt"]) + 1 if total_row else 1

        cursor = self.connection.execute(
            """
            INSERT INTO character_cycles (
                character_id, cycle_type, cycle_code,
                change_score, cumulative_score,
                batch_span, batch_micro_count, batch_summary,
                sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character_id, "micro", cycle_code,
                change_score, new_cumulative,
                str(data.get("batch_span", "") or ""),
                int(data.get("batch_micro_count", 0) or 0),
                str(data.get("batch_summary", "") or ""),
                sort_order,
            ),
        )
        cycle_id = int(cursor.lastrowid or 0)
        # 批次也累加增值
        self._add_change_score_no_commit(character_id, change_score)
        self.connection.commit()
        return cycle_id

    def update_micro_batch(self, cycle_id: int, batch_data: dict) -> None:
        """更新微循环批次日志。"""
        data = dict(batch_data or {})
        allowed = {"batch_span", "batch_micro_count", "batch_summary", "cycle_code"}
        filtered = {
            key: value for key, value in data.items() if key in allowed
        }
        if not filtered:
            return
        set_clause = ", ".join(
            f"{self._sql_identifier(col)} = ?" for col in filtered.keys()
        )
        params = [*filtered.values(), cycle_id]
        self.connection.execute(
            f"""
            UPDATE character_cycles
            SET {set_clause}
            WHERE id = ?
            """,
            tuple(params),
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # 快照存档
    # ------------------------------------------------------------------

    def list_snapshots(self, character_id: int) -> list:
        """列出快照存档，按 snapshot_no 升序。"""
        cursor = self.connection.execute(
            """
            SELECT *
            FROM character_snapshots
            WHERE character_id = ?
            ORDER BY snapshot_no ASC, id ASC
            """,
            (character_id,),
        )
        return list(cursor.fetchall())

    def create_snapshot(self, character_id: int, trigger_type: str,
                        trigger_detail: str, related_cycle_id: int | None = None,
                        phase_change_summary: str = '', micro_cycle_summary: str = '') -> int:
        """创建快照存档。从当前运行态快照复制字段。
        snapshot_no 自动递增 = 该 character 已有存档数 + 1。
        total_score_at_snapshot = 当前 total_change_score。
        返回新快照 id。"""
        snapshot_id = self._create_snapshot_no_commit(
            character_id,
            trigger_type=trigger_type,
            trigger_detail=trigger_detail,
            related_cycle_id=related_cycle_id,
            phase_change_summary=phase_change_summary,
            micro_cycle_summary=micro_cycle_summary,
        )
        self.connection.commit()
        return snapshot_id

    def get_latest_snapshot(self, character_id: int) -> sqlite3.Row | None:
        """获取最新一份快照存档（snapshot_no 最大）。"""
        cursor = self.connection.execute(
            """
            SELECT *
            FROM character_snapshots
            WHERE character_id = ?
            ORDER BY snapshot_no DESC, id DESC
            LIMIT 1
            """,
            (character_id,),
        )
        return cursor.fetchone()

    # ------------------------------------------------------------------
    # 增值计算
    # ------------------------------------------------------------------

    def add_change_score(self, character_id: int, score: int) -> tuple[int, bool]:
        """增加经验值，返回 (新累计值, 是否跨10倍门槛)。
        门槛判断：old // 10 < new // 10
        更新 character_state_machines.total_change_score。"""
        new_total, crossed = self._add_change_score_no_commit(character_id, score)
        self.connection.commit()
        return new_total, crossed

    # ------------------------------------------------------------------
    # 内部辅助：不自行 commit 的版本（供 create_cycle 在同事务内调用）
    # ------------------------------------------------------------------

    def _add_change_score_no_commit(self, character_id: int, score: int) -> tuple[int, bool]:
        """增加经验值（不 commit），返回 (新累计值, 是否跨10倍门槛)。"""
        sm_row = self.get_state_machine(character_id)
        old_total = int(sm_row["total_change_score"]) if sm_row else 0
        new_total = old_total + int(score)
        crossed_threshold = (old_total // 10) < (new_total // 10)
        self.connection.execute(
            """
            UPDATE character_state_machines
            SET total_change_score = ?, updated_at = CURRENT_TIMESTAMP
            WHERE character_id = ?
            """,
            (new_total, character_id),
        )
        return new_total, crossed_threshold

    def _update_running_snapshot_no_commit(self, character_id: int, snapshot: dict) -> None:
        """更新运行态快照（不 commit）。"""
        filtered = {
            key: value for key, value in (snapshot or {}).items()
            if key in RUNNING_SNAPSHOT_FIELDS
        }
        if not filtered:
            return
        set_clause = ", ".join(
            f"{self._sql_identifier(col)} = ?" for col in filtered.keys()
        )
        params = [*filtered.values(), character_id]
        self.connection.execute(
            f"""
            UPDATE character_state_machines
            SET {set_clause}, updated_at = CURRENT_TIMESTAMP
            WHERE character_id = ?
            """,
            tuple(params),
        )

    def _create_snapshot_no_commit(self, character_id: int, trigger_type: str,
                                   trigger_detail: str,
                                   related_cycle_id: int | None = None,
                                   phase_change_summary: str = '',
                                   micro_cycle_summary: str = '') -> int:
        """创建快照存档（不 commit），返回新快照 id。"""
        sm_row = self.get_state_machine(character_id)
        desire_state = str(sm_row["current_desire_state"]) if sm_row else ""
        mbti_state = str(sm_row["current_mbti_state"]) if sm_row else ""
        fate_state = str(sm_row["current_fate_state"]) if sm_row else ""
        belief_state = str(sm_row["current_belief_state"]) if sm_row else ""
        friction_level = str(sm_row["current_friction"]) if sm_row else ""
        phase_dilemma = str(sm_row["current_dilemma"]) if sm_row else ""
        total_score = int(sm_row["total_change_score"]) if sm_row else 0

        count_row = self.connection.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM character_snapshots
            WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        snapshot_no = int(count_row["cnt"]) + 1 if count_row else 1

        cursor = self.connection.execute(
            """
            INSERT INTO character_snapshots (
                character_id, snapshot_no, trigger_type, trigger_detail,
                related_cycle_id, desire_state, mbti_state, fate_state,
                belief_state, friction_level, phase_dilemma,
                phase_change_summary, micro_cycle_summary, total_score_at_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                character_id, snapshot_no, trigger_type, trigger_detail,
                related_cycle_id, desire_state, mbti_state, fate_state,
                belief_state, friction_level, phase_dilemma,
                phase_change_summary, micro_cycle_summary, total_score,
            ),
        )
        return int(cursor.lastrowid or 0)
