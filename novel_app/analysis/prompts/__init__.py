"""V3 分析链路外置提示词模板目录。

每个 `.md` 文件是一段系统提示词，首行 HTML 注释为元数据（会被加载器跳过）。
统一通过 :func:`load_prompt` 加载。
"""
from novel_app.analysis.prompts.loader import load_prompt

__all__ = ["load_prompt"]
