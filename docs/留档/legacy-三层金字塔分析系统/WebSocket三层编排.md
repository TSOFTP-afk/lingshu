# WebSocket 三层编排

> **归档声明**：本文件记录的三层金字塔 WebSocket 编排端点（`/ws/analysis`）已被 **V3 AI 增强 WebSocket** 替代。
> 新代码应使用 `/ws/analysis-v3` 端点（`lingshu_api.ws.analysis_v3_ws`）。
> 详见 `.trae/specs/ai-v3-replace-three-layer/spec.md`
>
> 本文档仅作留档参考，不再维护。

---

## 源文件位置

`lingshu_api/ws/analysis_ws.py`

---

## WebSocket 端点

```
路由: /ws/analysis
函数: ws_analysis(ws: WebSocket)
```

---

## 三层编排流程图

```
客户端连接 /ws/analysis
        │
        ▼
  ┌─────────────┐
  │  认证 WebSocket │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  接收 analyze 消息 │
  │  解析 book_id, analysis_mode │
  └──────┬──────┘
         │
         ▼
  ┌─────────────────────────────────┐
  │  判断 analysis_mode              │
  │  ┌───────────┐  ┌──────────────┐ │
  │  │ one_shot  │  │   pyramid    │ │
  │  └─────┬─────┘  └──────┬───────┘ │
  └────────┼───────────────┼─────────┘
           │               │
           ▼               ▼
  ┌─────────────┐  ┌──────────────────────────────────┐
  │ 一次性全书分析 │  │        三层金字塔分析              │
  │             │  │                                    │
  │ 检查字数限制  │  │  ┌────────────────────────────┐  │
  │ (< 400K字)  │  │  │ Level 1: 文本解读（并发）     │  │
  │ 检查模型能力  │  │  │ 对每个 source_block 调用      │  │
  │ (1M+ 上下文) │  │  │ analyze_book_level1          │  │
  │             │  │  │ 并发度: book_analysis_concurrency │
  │ 调用         │  │  │ 进度: 0% → 33%              │  │
  │ analyze_    │  │  └──────────────┬─────────────┘  │
  │ book_       │  │                 │                  │
  │ one_shot    │  │  ┌──────────────▼─────────────┐  │
  │             │  │  │ Level 2: 结构归并            │  │
  │ 进度:       │  │  │ 将全部 level1 结果合并        │  │
  │ full_book   │  │  │ 调用 analyze_book_level2    │  │
  │ 0% → 100%  │  │  │ 进度: 34% → 66%            │  │
  │             │  │  └──────────────┬─────────────┘  │
  │             │  │                 │                  │
  │             │  │  ┌──────────────▼─────────────┐  │
  │             │  │  │ Level 3: 草案生成            │  │
  │             │  │  │ 调用 analyze_book_level3_   │  │
  │             │  │  │         draft               │  │
  │             │  │  │ 进度: 67% → 83%            │  │
  │             │  │  └──────────────┬─────────────┘  │
  │             │  │                 │                  │
  │             │  │     ┌─── 有 source_requests? ───┐ │
  │             │  │     │ 是                        │ 否│
  │             │  │     ▼                           │  │
  │             │  │  ┌──────────────────────┐       │  │
  │             │  │  │ 原文回查与复核         │       │  │
  │             │  │  │ 构建 source_context    │       │  │
  │             │  │  │ 调用 analyze_book_     │       │  │
  │             │  │  │   level3_finalize      │       │  │
  │             │  │  │ 进度: 84% → 99%       │       │  │
  │             │  │  └──────────┬───────────┘       │  │
  │             │  │             │                    │  │
  │             │  │             └────────┬───────────┘  │
  │             │  │                      │              │
  │             │  │                      ▼              │
  │             │  │           ┌──────────────────┐     │
  │             │  │           │ 创建 draft_run    │     │
  │             │  │           │ pipeline.create_  │     │
  │             │  │           │   draft_run       │     │
  │             │  │           │ 记录 AI 用量       │     │
  │             │  │           └──────────────────┘     │
  └──────┬──────┘  └──────────────────────────────────┘
         │
         ▼
  ┌─────────────┐
  │ 返回 result 消息 │
  │ 含 run_id,      │
  │ card_count,     │
  │ block_count     │
  └─────────────┘
```

---

## WebSocket 消息类型

### 客户端 → 服务器

#### `analyze` — 发起分析请求

```json
{
  "type": "analyze",
  "task_id": "uuid-string",
  "payload": {
    "book_id": 123,
    "analysis_mode": "pyramid"  // 或 "one_shot"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `str` | 固定为 `"analyze"` |
| `task_id` | `str` | 客户端生成的任务 ID |
| `payload.book_id` | `int` | 要分析的作品 ID |
| `payload.analysis_mode` | `str` | 分析模式：`"pyramid"`（默认）或 `"one_shot"` |

`analysis_mode` 可选值：
- `"pyramid"` — 三层金字塔分析（默认）
- `"one_shot"` / `"oneshot"` / `"full_book"` / `"一次性读完"` — 一次性全书分析

#### `cancel` — 取消分析

```json
{
  "type": "cancel",
  "task_id": "uuid-string"
}
```

---

### 服务器 → 客户端

#### `progress` — 进度推送

```json
{
  "type": "progress",
  "task_id": "uuid-string",
  "payload": {
    "stage": "level1",
    "percent": 15,
    "message": "level1 片段 3/20"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `payload.stage` | `str` | 当前阶段标识 |
| `payload.percent` | `int` | 总体进度百分比（0-100） |
| `payload.message` | `str` | 人类可读的进度描述 |

**stage 取值**：

| stage | 含义 | percent 范围 |
|-------|------|-------------|
| `"level1"` | 第一级文本解读 | 0 ~ 33 |
| `"level2"` | 第二级结构归并 | 34 ~ 66 |
| `"level3"` | 第三级草案生成 | 67 ~ 83 |
| `"source_review"` | 原文回查与复核 | 84 ~ 99 |
| `"full_book"` | 一次性全书分析 | 0 ~ 100 |

#### `result` — 分析完成

```json
{
  "type": "result",
  "task_id": "uuid-string",
  "payload": {
    "status": "ok",
    "run_id": 456,
    "card_count": 12,
    "block_count": 30,
    "findings": [],
    "summary": "全书分析完成：20 章，生成 12 张草案卡"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `payload.status` | `str` | `"ok"` 或 `"cancelled"` |
| `payload.run_id` | `int` | 分析运行 ID |
| `payload.card_count` | `int` | 生成的草案卡数量 |
| `payload.block_count` | `int` | 分析块数量 |
| `payload.findings` | `list` | level1 结果（pyramid 模式）或空列表（one_shot 模式） |
| `payload.summary` | `str` | 分析摘要文本 |

#### `error` — 错误消息

```json
{
  "type": "error",
  "task_id": "uuid-string",
  "payload": {
    "message": "错误描述"
  }
}
```

#### `deprecation_warning` — 废弃警告

```json
{
  "type": "deprecation_warning",
  "task_id": "uuid-string",
  "payload": {
    "message": "三层金字塔分析系统已废弃，建议使用 V3 AI 增强分析（/ws/analysis-v3）。",
    "deprecated_endpoint": "/ws/analysis",
    "replacement_endpoint": "/ws/analysis-v3"
  }
}
```

首次收到 `analyze` 请求时自动推送一次。

---

## Level 1 编排逻辑（并发）

```python
# 核心代码逻辑（简化）
level1_results: list[dict | None] = [None] * len(source_blocks)
semaphore = asyncio.Semaphore(concurrency)  # 默认并发度 3

async def _guarded_level1(index, chunk):
    async with semaphore:
        return await loop.run_in_executor(None, lambda: ai_service.analyze_book_level1(
            book_title=book["title"],
            book_outline=book["outline_text"],
            chunk_text=chunk["text"],
            chunk_index=index + 1,
            total_chunks=len(source_blocks),
            chunk_id=chunk.get("chunk_id") or str(index),
            chapter_ids=chunk.get("chapter_ids", []),
            extra_body=fast_extra_body,
            require_remote=True,
        ))

# 为每个 source_block 创建并发任务
level1_tasks = [asyncio.create_task(_guarded_level1(i, chunk)) for i, chunk in enumerate(source_blocks)]

# 逐个完成，推送进度
for task in asyncio.as_completed(level1_tasks):
    chunk_idx, result = await task
    level1_results[chunk_idx] = result
    completed_level1 += 1
    # 推送进度: percent = int((completed_level1 / total) * 33)
```

**关键特性**：
- 使用 `asyncio.Semaphore` 控制并发度
- 每完成一个 chunk 立即推送进度
- 支持通过 `cancel_event` 取消
- 进度映射到 0%~33% 区间

---

## Level 2 编排逻辑（单次归并）

```python
# 核心代码逻辑（简化）
level2_result = await loop.run_in_executor(None, lambda: ai_service.analyze_book_level2(
    book_title=book["title"],
    level1_results=level1_results,
    group_index=1,
    total_groups=1,
    extra_body=fast_extra_body,
    require_remote=True,
))
level2_results = level2_result if isinstance(level2_result, list) else [level2_result]
```

**关键特性**：
- 将全部 level1 结果一次性传入（group_index=1, total_groups=1）
- 进度映射到 34%~66% 区间
- 返回值兼容 list 和 dict 两种格式

---

## Level 3 编排逻辑（草案 + 可选复核）

```python
# 草案生成
draft_payload = await loop.run_in_executor(None, lambda: ai_service.analyze_book_level3_draft(
    book_title=book["title"],
    book_outline=book["outline_text"],
    level2_results=level2_results,
    chapters=chapters,
    characters=db.list_characters(book_id),
    world_entries=db.db.list_world_entries(book_id),
    source_index=source_blocks,
    extra_body=final_extra_body,
    require_remote=True,
))

# 检查是否需要原文回查
source_requests = _source_requests(draft_payload)

if source_requests:
    # 构建回查上下文
    source_context = _build_source_review_context(source_requests, source_blocks)

    # 原文复核
    final_payload = await loop.run_in_executor(None, lambda: ai_service.analyze_book_level3_finalize(
        book_title=book["title"],
        book_outline=book["outline_text"],
        level2_results=level2_results,
        draft_payload=draft_payload,
        source_context=source_context,
        chapters=chapters,
        characters=db.list_characters(book_id),
        world_entries=db.db.list_world_entries(book_id),
        extra_body=final_extra_body,
        require_remote=True,
    ))
```

**关键特性**：
- 草案阶段进度 67%~83%
- 原文回查阶段进度 84%~99%
- `_source_requests` 从草案中提取 `source_requests`/`verification_requests` 字段
- `_build_source_review_context` 根据请求匹配原文块（最多 10 块，每块最多 5000 字符）

---

## One-Shot 编排逻辑

```python
# 前置检查
if book_char_count >= ONE_SHOT_BOOK_CHAR_LIMIT:  # 400,000 字
    # 报错：字数超限
if not model_capability.get("matched"):
    # 报错：模型不支持 1M+ 上下文

# 执行
final_payload = await loop.run_in_executor(None, lambda: ai_service.analyze_book_one_shot(
    book_title=book["title"],
    book_outline=book["outline_text"],
    chapters=chapters,
    source_blocks=source_blocks,
    characters=db.list_characters(book_id),
    world_entries=db.db.list_world_entries(book_id),
    extra_body=final_extra_body,
    require_remote=True,
))
```

**前置条件**：
- 正文总字数 < 400,000 字
- 当前模型在长上下文模型支持表中（1M+ tokens）

---

## 辅助函数

| 函数 | 功能 |
|------|------|
| `_connection_user` | 从 WebSocket 管理器获取连接用户信息 |
| `_record_analysis_usage` | 记录分析运行和 AI 用量 |
| `_build_chunks` | 将章节切分为指定大小的文本块（max_chars=20000） |
| `_create_analysis_retriever` | 创建 RAG 检索器 |
| `_consume_task_exception` | 消费异步任务异常，防止未处理异常警告 |
| `_book_content_char_count` | 计算章节正文总字数（去除空白） |
| `_requested_analysis_mode` | 解析分析模式字符串为 `"one_shot"` 或 `"pyramid"` |
| `_validate_one_shot_payload` | 验证 one-shot 返回的 payload 非空 |
| `_has_one_shot_writeback_content` | 检查 payload 是否包含可写回内容 |
| `_has_content` | 递归检查值是否非空 |
| `_attach_analysis_meta` | 为 payload 附加 `_requires_evidence` 和 `_meta` |
| `_analysis_run_meta` | 构建分析运行的元数据 |
| `_analysis_common_meta` | 构建通用分析元数据 |
| `_json_extra_body` | 解析 extra_body JSON 配置 |
| `_positive_int` | 安全转换为正整数 |
| `_source_requests` | 从草案 payload 中提取 source_requests |
| `_build_source_review_context` | 根据 source_requests 匹配并构建原文回查上下文 |
| `_block_matches_request` | 判断原文块是否匹配回查请求（UID/章节ID/关键词） |
| `_source_context_block` | 将原文块格式化为回查上下文格式 |

---

## 配置项

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `book_analysis_concurrency` | 3 | Level 1 并发度 |
| `book_analysis_fast_extra_body` | `None` | Level 1/2 的额外 API 参数（JSON 字符串） |
| `book_analysis_final_extra_body` | `None` | Level 3 的额外 API 参数（JSON 字符串） |
| `ONE_SHOT_BOOK_CHAR_LIMIT` | 400,000 | One-shot 模式字数上限 |
