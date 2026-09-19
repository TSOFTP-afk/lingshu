"""提示词模板加载器。

`novel_app/analysis/prompts/` 下每个 `.md` 文件对应一段外置的系统提示词，
首行为一行 HTML 注释（`<!-- ... -->`）说明用途与消费方法，其余内容为提示词原文。

`load_prompt` 返回提示词原文（跳过首行元数据注释），不做任何 strip/trim——
消费处的既有处理逻辑（strip、切片等）全部保留在调用方代码里。
"""
from __future__ import annotations

import functools
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@functools.cache
def load_prompt(name: str) -> str:
    """按文件名（不含扩展名）加载提示词模板，返回提示词原文。

    - functools.cache（即 lru_cache(maxsize=None)）进程内每个文件只读一次磁盘。
    - 若文件首行是以 ``<!--`` 开头的 HTML 注释（本目录约定的元数据行），跳过该行；
      其余字节原样返回，与外置前的字符串字面量逐字节一致。
    """
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if text.startswith("<!--"):
        first_line_end = text.find("\n")
        if first_line_end != -1:
            return text[first_line_end + 1 :]
    return text
