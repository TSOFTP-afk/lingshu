from __future__ import annotations

from novel_app.db.common import *


class ChapterGenerationSnapshotMixin:
    # ------------------------------------------------------------------
    # 生成快照 CRUD
    # ------------------------------------------------------------------

    def list_generation_snapshots(self, chapter_id: int) -> list:
        """列出章节的生成快照，按 created_at DESC 排序。返回 list[dict]。"""
        cursor = self.connection.execute(
            """
            SELECT id, chapter_id, mode, outline, generated_text,
                   selected_skills_json, status, task_id, created_at
            FROM chapter_generation_snapshots
            WHERE chapter_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (chapter_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def create_generation_snapshot(self, chapter_id: int, data: dict) -> int:
        """创建生成快照。data 含 mode/outline/generated_text/selected_skills/status/task_id。
        selected_skills 是 list[dict]，需 json.dumps 存入 selected_skills_json。
        返回新快照 id。"""
        d = dict(data or {})
        selected_skills = d.get("selected_skills", [])
        if isinstance(selected_skills, str):
            selected_skills_json = selected_skills
        else:
            selected_skills_json = json.dumps(selected_skills, ensure_ascii=False)
        cursor = self.connection.execute(
            """
            INSERT INTO chapter_generation_snapshots (
                chapter_id, mode, outline, generated_text,
                selected_skills_json, status, task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                str(d.get("mode", "draft") or "draft"),
                str(d.get("outline", "") or ""),
                str(d.get("generated_text", "") or ""),
                selected_skills_json,
                str(d.get("status", "success") or "success"),
                str(d.get("task_id", "") or ""),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def get_generation_snapshot(self, snapshot_id: int) -> sqlite3.Row | None:
        """获取单条快照。"""
        cursor = self.connection.execute(
            """
            SELECT id, chapter_id, mode, outline, generated_text,
                   selected_skills_json, status, task_id, created_at
            FROM chapter_generation_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        )
        return cursor.fetchone()

    def delete_generation_snapshot(self, snapshot_id: int) -> None:
        """删除快照。"""
        self.connection.execute(
            "DELETE FROM chapter_generation_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        self.connection.commit()

    def restore_generation_snapshot(self, snapshot_id: int) -> dict | None:
        """恢复快照到正文。

        1. 读取快照获取 chapter_id 与 generated_text
        2. 读取 chapter 当前 content（及 outline）
        3. 把旧 content 存入 chapter_snapshots 表（label='generation_restore'）
        4. 把 generated_text 写入 chapters.content
        5. 返回 {chapter_id, old_content_length, new_content_length}

        若快照不存在返回 None。

        多表写入（chapter_snapshots + chapters），不在方法内自行 commit，
        由调用方的 transaction() 统一管理。"""
        snapshot = self.get_generation_snapshot(snapshot_id)
        if snapshot is None:
            return None
        chapter_id = int(snapshot["chapter_id"])
        generated_text = str(snapshot["generated_text"] or "")

        chapter = self.connection.execute(
            "SELECT content, outline FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        old_content = str(chapter["content"]) if chapter else ""
        old_outline = str(chapter["outline"]) if chapter else ""

        # 旧 content 存入 chapter_snapshots（label 标记来源）
        self.connection.execute(
            """
            INSERT INTO chapter_snapshots (chapter_id, label, outline, content)
            VALUES (?, ?, ?, ?)
            """,
            (chapter_id, "generation_restore", old_outline, old_content),
        )

        # 写入新正文
        self.connection.execute(
            "UPDATE chapters SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (generated_text, chapter_id),
        )

        return {
            "chapter_id": chapter_id,
            "old_content_length": len(old_content),
            "new_content_length": len(generated_text),
        }
