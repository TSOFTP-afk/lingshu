"""打印 V3 AI 分析中实际发送给 LLM 的 prompt 内容。

通过拦截 _call_llm 方法来捕获 system_prompt 和 user_prompt。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.ai.service import SimpleAIService
from novel_app.analysis.ai_provider import AIAnalysisProvider
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.database import Database

os.environ.setdefault("LINGSHU_AI_API_KEY", "sk-test-placeholder")
os.environ["LINGSHU_AI_BASE_URL"] = "https://api.deepseek.com/v1"
os.environ["LINGSHU_AI_MODEL"] = "deepseek-chat"

CHAPTERS = [
    ("第一章 陨落的天才", """
斗之力，三段！
望着测验魔石碑上面闪亮得甚至有些刺眼的五个大字，少年面无表情，唇角有着一抹自嘲...

"萧炎，斗之力，三段！级别：低级！"测验魔石碑之旁，一位中年男子，语气漠然公布。

"下一个，萧媚！"

"萧媚，斗之气：七段！级别：高级！"

"下一个，萧薰儿！"

"斗之气：九段！级别：高级！"

"萧炎哥哥。"萧薰儿对着萧炎恭敬弯了弯腰。

房间中，一个苍老的声音从戒指中响起："小家伙，想知道为什么你的斗之气消失吗？"

"老夫药尘，人称药尊者。这三年，你修炼出来的斗之气，全都被老夫给吸收了！"

"小子别急，从今天起，老夫教你炼药术，让你成为这斗气大陆上最强的炼药师！"
"""),
    ("第二章 斗气大陆", """
翌日清晨，萧炎从修炼中醒来，按照药尘的指导，他昨晚尝试了一套新的修炼功法——焚决。

演武场上，萧宁站在场中央，朗声道："萧炎表弟，要不要来切磋一下？"

萧炎平静看着萧宁："你想打，我便陪你。"

萧宁一拳袭来，萧炎脚步轻移险险避开，一掌正中萧宁胸口。
"""),
    ("第三章 炼药初试", """
萧炎盘坐房间中，面前摆放着紫兰草、凝血花、骨灵果等药材。

"炼药师的基础，便是从这些低级药材开始。"萧炎平静道。

药尘赞许："现在，尝试炼制一枚凝血散。"

萧炎掌心凝聚出淡黄色斗气火焰，小心翼翼投入紫兰草。

"成功了！"

"凝血散，一品丹药，可加速伤口愈合。"

萧炎眼中闪过一抹坚定："总有一天，我会炼制出九品丹药，成为这大陆上最强的炼药师！"
"""),
]


class PromptInspector(AIAnalysisProvider):
    """拦截 _call_llm 打印 prompt 的 AI 分析器。"""

    call_index = 0
    MAX_PRINT = 5  # 只打印前 N 次调用的 prompt

    def _call_llm(self, *, stage, input_payload, system_prompt, user_prompt, temperature=0.2):
        PromptInspector.call_index += 1
        idx = PromptInspector.call_index

        if idx <= self.MAX_PRINT:
            self._print_prompt(idx, stage, input_payload, system_prompt, user_prompt, temperature)

        # 仍然调用真实 LLM
        return super()._call_llm(
            stage=stage, input_payload=input_payload,
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=temperature,
        )

    @staticmethod
    def _print_prompt(idx, stage, input_payload, system_prompt, user_prompt, temperature):
        print(f"\n{'='*80}")
        print(f"[调用 #{idx}] stage={stage} | temperature={temperature}")
        print(f"{'='*80}")

        # ── 输入元数据 ──
        meta = {}
        for k in ("book_id", "block_uid", "window_index", "window_start", "window_end",
                   "mentions_count", "probe_type", "probe_uid"):
            if k in input_payload:
                meta[k] = input_payload[k]
        if meta:
            print(f"元数据: {json.dumps(meta, ensure_ascii=False)}")

        # ── 完整 system prompt ──
        print(f"\n--- SYSTEM PROMPT ({len(system_prompt)} 字符) ---")
        print(system_prompt)

        # ── user prompt ──
        print(f"\n--- USER PROMPT ({len(user_prompt)} 字符) ---")
        if "文本片段：" in user_prompt:
            parts = user_prompt.split("文本片段：\n", 1)
            print(parts[0] + "文本片段：")
            if len(parts) > 1:
                text_content = parts[1]
                for suffix in ("\n\n请抽取其中的实体提及。",
                               "\n\n请抽取原子事实，subject_entity_uid 必须来自已知实体列表。",
                               "\n\n请将指代同一实体的提及合并，返回实体列表。"):
                    if text_content.endswith(suffix):
                        text_content = text_content[: -len(suffix)]
                        break
                print(f"<文本内容, {len(text_content)} 字符>")
                print(text_content[:600])
                if len(text_content) > 600:
                    print(f"... (省略 {len(text_content) - 600} 字符)")
                for suffix in ("\n\n请抽取其中的实体提及。",
                               "\n\n请抽取原子事实，subject_entity_uid 必须来自已知实体列表。",
                               "\n\n请将指代同一实体的提及合并，返回实体列表。"):
                    if user_prompt.endswith(suffix):
                        print(suffix.strip())
                        break
        else:
            if len(user_prompt) > 2000:
                print(user_prompt[:2000])
                print(f"... (省略 {len(user_prompt) - 2000} 字符)")
            else:
                print(user_prompt)

        total_chars = len(system_prompt) + len(user_prompt)
        print(f"\n  总字符数: {total_chars}, 估算约 {total_chars // 2} tokens")


def main():
    print("灵枢 V3 — AI Prompt 审查")
    print("=" * 80)

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("斗破苍穹")
            for title, content in CHAPTERS:
                ch_id = db.create_chapter(book_id, title)
                db.update_chapter(ch_id, outline="", content=content)
            for name in ["萧炎", "萧薰儿", "萧媚", "药尘", "萧战", "萧宁"]:
                db.create_character(book_id, name)

            ai_service = SimpleAIService(
                api_key=os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
            )
            llm_cache = LLMCache(db)
            inspector = PromptInspector(ai_service, llm_cache)

            print("\n启动分析...\n")
            result = AnalysisPipelineV3(db, ai_provider=inspector).start_run(
                book_id, use_ai=True
            )

            print(f"\n{'='*80}")
            print(f"总计: {PromptInspector.call_index} 次 AI 调用")
            print(f"状态: {result.status}")
            print(f"{'='*80}")

        finally:
            db.close()


if __name__ == "__main__":
    main()
