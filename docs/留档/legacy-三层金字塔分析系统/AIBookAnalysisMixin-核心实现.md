# AIBookAnalysisMixin 核心实现

> **归档声明**：本文件记录的三层金字塔分析系统（`AIBookAnalysisMixin`）已被 **V3 AI 增强模式**替代。
> 新代码应使用 `novel_app.analysis.pipeline_v3.AnalysisPipelineV3(use_ai=True)`。
> 详见 `.trae/specs/ai-v3-replace-three-layer/spec.md`
>
> 本文档仅作留档参考，不再维护。

---

## 源文件位置

`novel_app/ai_book_analysis.py`

---

## 类概览

`AIBookAnalysisMixin` 是一个 Mixin 类，为 AI 服务提供全书分析能力。它实现了三层金字塔分析逻辑，以及一次性全书分析（one-shot）的降级路径。

---

## 公开方法

### 1. `analyze_book`

```python
def analyze_book(
    self,
    *,
    book_title: str,
    book_outline: str,
    chapters: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    world_entries: list[dict[str, Any]] | None = None,
    require_remote: bool = False,
) -> dict[str, Any]
```

**功能**：分析整本书并返回标准化的分析结果 payload。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `book_title` | `str` | 书名 |
| `book_outline` | `str` | 书籍级设定/大纲文本 |
| `chapters` | `list[dict]` | 章节列表，每项含 id、title、outline、content |
| `characters` | `list[dict] \| None` | 现有人物卡列表 |
| `world_entries` | `list[dict] \| None` | 现有世界观条目列表 |
| `require_remote` | `bool` | 是否强制要求远程 AI 调用 |

**返回值**：`dict[str, Any]` — 包含 `book_outline`、`characters`、`world_entries`、`chapter_updates` 等字段的分析结果。

**逻辑**：优先尝试远程 AI 分析（`_analyze_book_remote`），失败时回退到 mock 分析（`_analyze_book_mock`）。

---

### 2. `analyze_book_level1`

```python
def analyze_book_level1(
    self,
    *,
    book_title: str,
    book_outline: str,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    chunk_id: str = "",
    chapter_ids: list[int] | None = None,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：执行第一级分析——对单个原文片段进行忠实解读。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `book_title` | `str` | 书名 |
| `book_outline` | `str` | 书籍级设定 |
| `chunk_text` | `str` | 当前片段的原文文本 |
| `chunk_index` | `int` | 当前片段序号（从 1 开始） |
| `total_chunks` | `int` | 片段总数 |
| `chunk_id` | `str` | 片段唯一标识 |
| `chapter_ids` | `list[int] \| None` | 该片段覆盖的章节 ID 列表 |
| `extra_body` | `dict \| None` | 传递给 AI API 的额外参数 |
| `require_remote` | `bool` | 是否强制要求远程 AI 调用 |

**返回值**：`dict[str, Any]` — 包含 `level`、`chunk_index`、`total_chunks`、`faithful_digest`、`key_events`、`character_clues`、`world_clues`、`chapter_updates`、`source_facts` 等字段。

**注意**：此方法已标记 `DeprecationWarning`。

---

### 3. `analyze_book_level2`

```python
def analyze_book_level2(
    self,
    *,
    book_title: str,
    level1_results: list[dict[str, Any]],
    group_index: int,
    total_groups: int,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：执行第二级分析——将多个第一级结果归并为结构化摘要。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `book_title` | `str` | 书名 |
| `level1_results` | `list[dict]` | 第一级分析结果列表 |
| `group_index` | `int` | 当前二级分组序号 |
| `total_groups` | `int` | 二级分组总数 |
| `extra_body` | `dict \| None` | 传递给 AI API 的额外参数 |
| `require_remote` | `bool` | 是否强制要求远程 AI 调用 |

**返回值**：`dict[str, Any]` — 包含 `level`、`group_index`、`total_groups`、`story_summary`、`logic_chain`、`timeline`、`character_arcs`、`world_model`、`chapter_updates`、`output_hints`、`consolidated_facts`、`conflicts`、`coverage_gaps` 等字段。

**注意**：此方法已标记 `DeprecationWarning`。

---

### 4. `analyze_book_level3`

```python
def analyze_book_level3(
    self,
    *,
    book_title: str,
    book_outline: str,
    level2_results: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    world_entries: list[dict[str, Any]] | None = None,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：执行第三级分析——生成最终可写回的分析输出。内部委托给 `_analyze_book_level3_draft_remote`（无 source_index）。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `book_title` | `str` | 书名 |
| `book_outline` | `str` | 书籍级设定 |
| `level2_results` | `list[dict]` | 第二级分析结果列表 |
| `chapters` | `list[dict]` | 章节列表 |
| `characters` | `list[dict] \| None` | 现有人物卡列表 |
| `world_entries` | `list[dict] \| None` | 现有世界观条目列表 |
| `extra_body` | `dict \| None` | 传递给 AI API 的额外参数 |
| `require_remote` | `bool` | 是否强制要求远程 AI 调用 |

**返回值**：`dict[str, Any]` — 包含 `book_outline`、`book_outline_form`、`world_form`、`characters`、`chapter_updates`、`analysis_unresolved` 等字段。

**注意**：此方法已标记 `DeprecationWarning`。

---

### 5. `analyze_book_level3_draft`

```python
def analyze_book_level3_draft(
    self,
    *,
    book_title: str,
    book_outline: str,
    level2_results: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    world_entries: list[dict[str, Any]] | None = None,
    source_index: list[dict[str, Any]] | None = None,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：生成第三级草案（证据复核前）。与 `analyze_book_level3` 的区别在于支持传入 `source_index` 用于原文回查。

**参数**：与 `analyze_book_level3` 基本相同，额外增加：
| 参数 | 类型 | 说明 |
|------|------|------|
| `source_index` | `list[dict] \| None` | 可回查的原文块索引，用于证据引用 |

**返回值**：同 `analyze_book_level3`，但草案中可能包含 `source_requests` 字段。

**注意**：此方法已标记 `DeprecationWarning`。

---

### 6. `analyze_book_level3_finalize`

```python
def analyze_book_level3_finalize(
    self,
    *,
    book_title: str,
    book_outline: str,
    level2_results: list[dict[str, Any]],
    draft_payload: dict[str, Any],
    source_context: dict[str, Any],
    chapters: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    world_entries: list[dict[str, Any]] | None = None,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：基于草案和原文回查结果，进行第三级最终复核，输出可写回的最终 JSON。

**参数**：与 `analyze_book_level3` 基本相同，额外增加：
| 参数 | 类型 | 说明 |
|------|------|------|
| `draft_payload` | `dict` | 第三级草案的 payload |
| `source_context` | `dict` | 回查到的原文片段上下文 |

**返回值**：最终可写回的分析 payload，字段同 `analyze_book_level3`。

---

### 7. `analyze_book_one_shot`

```python
def analyze_book_one_shot(
    self,
    *,
    book_title: str,
    book_outline: str,
    chapters: list[dict[str, Any]],
    source_blocks: list[dict[str, Any]],
    characters: list[dict[str, Any]] | None = None,
    world_entries: list[dict[str, Any]] | None = None,
    extra_body: dict[str, Any] | None = None,
    require_remote: bool = True,
) -> dict[str, Any]
```

**功能**：对短篇幅书籍进行一次性全书分析（长上下文模型，1M+ tokens）。

**参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `book_title` | `str` | 书名 |
| `book_outline` | `str` | 书籍级设定 |
| `chapters` | `list[dict]` | 章节列表 |
| `source_blocks` | `list[dict]` | 完整原文块列表 |
| `characters` | `list[dict] \| None` | 现有人物卡列表 |
| `world_entries` | `list[dict] \| None` | 现有世界观条目列表 |
| `extra_body` | `dict \| None` | 传递给 AI API 的额外参数 |
| `require_remote` | `bool` | 是否强制要求远程 AI 调用 |

**返回值**：`dict[str, Any]` — 包含 `_requires_evidence`、`book_outline`、`book_outline_form`、`world_form`、`characters`、`chapter_updates`、`analysis_unresolved` 等字段。

---

## 私有方法

### `_analyze_book_level1_remote`
远程执行第一级分析。构建 prompt 要求 AI 忠实解读原文片段，输出 JSON 含 `faithful_digest`、`key_events`、`character_clues`、`world_clues`、`chapter_updates`、`source_facts`。

### `_analyze_book_level2_remote`
远程执行第二级分析。将多个 level1 结果归并，输出 `story_summary`、`logic_chain`、`timeline`、`character_arcs`、`world_model`、`consolidated_facts`、`conflicts`、`coverage_gaps`。

### `_analyze_book_level3_draft_remote`
远程执行第三级草案生成。整合全部 level2 结果，按模板填写 `book_outline_form`、`world_form`、`characters.profile_form`、`chapter_updates`，并输出 `source_requests` 供后续回查。

### `_analyze_book_level3_remote`
委托给 `_analyze_book_level3_draft_remote`（source_index 为空列表），是 `analyze_book_level3` 的内部实现。

### `_analyze_book_level3_finalize_remote`
远程执行第三级原文复核。基于草案和回查原文，输出最终可写回 JSON，删除无证据字段，保留 `evidence_refs`/`source_quotes`。

### `_analyze_book_one_shot_remote`
远程执行一次性全书分析。将完整 source_blocks 一次性发送给长上下文模型，直接输出最终 JSON。

### `_analyze_book_remote`
远程执行全书分析（非分层，旧版单次分析）。将章节内容截断后一次性发送给 AI。

### `_analyze_book_mock`
本地 mock 分析。不调用 AI，基于章节内容生成简单摘要和章节更新。

---

## 方法调用关系图

```
analyze_book
├── _analyze_book_remote          （远程：旧版单次分析）
│   └── _post_json_chat_completion
│       └── _chat_completion_content → _extract_json_object_payload
└── _analyze_book_mock            （本地：mock 降级）

analyze_book_level1
└── _analyze_book_level1_remote
    └── _post_json_chat_completion
        └── _chat_completion_content → _extract_json_object_payload

analyze_book_level2
└── _analyze_book_level2_remote
    └── _post_json_chat_completion
        └── _chat_completion_content → _extract_json_object_payload

analyze_book_level3
└── _analyze_book_level3_remote
    └── _analyze_book_level3_draft_remote（source_index=[]）
        └── _post_json_chat_completion
            └── _chat_completion_content → _extract_json_object_payload

analyze_book_level3_draft
└── _analyze_book_level3_draft_remote（source_index=传入值）
    └── _post_json_chat_completion
        └── _chat_completion_content → _extract_json_object_payload

analyze_book_level3_finalize
└── _analyze_book_level3_finalize_remote
    └── _post_json_chat_completion
        └── _chat_completion_content → _extract_json_object_payload

analyze_book_one_shot
└── _analyze_book_one_shot_remote
    └── _post_json_chat_completion
        └── _chat_completion_content → _extract_json_object_payload
```

---

## 依赖项

| 模块 | 用途 |
|------|------|
| `novel_app.ai_limits` | 各级分析的 max_tokens 限制 |
| `novel_app.ai_types` | `DEFAULT_BASE_URL`、`SkillCard` |
| `novel_app.json_utils` | JSON 提取、修复、解析工具 |
| `novel_app.prompt_utils` | prompt 模板工具 |
| `novel_app.structured_templates` | 书籍级/世界观/人物模板和 schema |

---

## 辅助函数

### `_raise_if_chat_completion_truncated`

```python
def _raise_if_chat_completion_truncated(result: dict[str, Any], purpose: str) -> None
```

检查 AI 返回是否因 `max_tokens` 被截断（`finish_reason == "length"`），若是则抛出 `RuntimeError`。
