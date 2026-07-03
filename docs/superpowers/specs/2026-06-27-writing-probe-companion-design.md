# 写作探针伴随机制设计

- 日期：2026-06-27
- 状态：已确认，待实现
- 范围：前端（lingshu-app）+ 后端（lingshu_api / novel_app）

## 1. 目标

1. 在 AI 设置中新增"写作探针"用途配置（开关 / 模型 / 间隔 / 阈值）。
2. 在工作台抽屉新增"探针"tab，承载每章独立草稿（章节概要 + 章节人物）。
3. 作者在 ContentEditor 写作时按配置间隔（默认 8 秒）后台静默扫描当前章节，将章节概要和发现的人物以草稿形式保存到探针界面。
4. 探针界面提供"采纳"和"一键写回全部"按钮，复用现有 V3 writeback 机制写回正式业务表（characters / chapters.summary_text）。
5. 工作台"人物"tab 新增章节过滤视图：用规则（MentionExtractor + 现有 characters 作为种子）匹配当前章节出现的所有人物，按出现次数排序展示。

## 2. 非目标

- 不修改 V3 pipeline 主流程、不修改 probe_planner / probe_executor（被动探针）/ active_probe_executor（主动探针）。
- 不删除后端实体（entity）相关 API 与数据，V3 pipeline M3/M3+ 仍依赖实体表。
- 不实现"分析阶段概览/当前阶段"UI 改造（用户在前一轮澄清中已转向探针方案，原 UI 改造搁置）。
- 不实现自动写回（所有写回都需用户手动点击"采纳"或"一键写回全部"）。

## 3. 现状关键事实

- AI 设置主组件：`lingshu-app/src/components/settings/AiSettingsSection.vue`，9 个用途定义在 `lingshu_api/services/ai_settings.py` L14-24（writing/outline/detector/correction/import/skills/book_analysis/review/chat）。
- AI 设置持久化：`data/ai_settings.json`，加密存储 api_key。
- 工作台抽屉：`lingshu-app/src/components/drawer/DrawerPanel.vue`，9 个 tab（overview/shortcuts/characters/world/skills/generate/analysis/review/tasks）。
- 章节编辑器：`lingshu-app/src/components/workspace/ContentEditor.vue`，目前无任何分析联动。
- 章节状态：`bookStore.activeChapterId`（`lingshu-app/src/stores/book.js` L24）。
- CharactersTab：`lingshu-app/src/components/drawer/CharactersTab.vue`，当前只按 bookId 加载全书人物，无章节感知（无 defineProps，无 chapterId watch）。
- 后端章节保存：`PATCH /api/workspace/chapters/{chapter_id}`，只更新 content/title，不触发概要生成。
- 章节概要字段：`chapters.summary_text`（schema 已有，但 workspace 路由层无生成入口）。
- MentionExtractor：`novel_app/analysis/mention_extractor.py`，刚优化完成，对话/动作模式精度 100%（Book 6 实测 6 命中 6 真实人物 0 误报）。
- V3 writeback：`novel_app/analysis/v3_writeback.py` 的 `writeback_v3_card`，已支持 character/world_entry/book 三类写回，含 schema gate + snapshot（analysis_apply_snapshots 表）+ 审计日志。
- 写回端点：`POST /api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback`（已有，限流 10/min）。
- analysis_cards 表：`novel_app/db/schema.py` L384-404，status 流转 draft → applied，payload_json 承载 writeback_target/writeback_fields。

## 4. 设计

### 4.1 探针配置（AI 设置新增用途）

**新增用途** `writing_probe`，复用现有 profile 结构（provider/api_key/base_url/model/temperature/max_tokens/thinking_*），并扩展三个探针专属字段：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | false | 探针总开关 |
| `interval_seconds` | int | 8 | 扫描间隔（5-60，防抖下限） |
| `auto_write_threshold` | float | 0.55 | 入草稿的置信度阈值（等于 MentionExtractor MENTION_MIN_CONFIDENCE） |

**前端**：`AiSettingsSection.vue` 的"按用途配置"面板（L141-263）新增 `writing_probe` tab，字段同其他用途 + 三个探针专属字段（enabled 开关、interval 数字输入、threshold 滑块）。

**后端**：
- `lingshu_api/services/ai_settings.py` 的 `AI_PURPOSES`（L14-24）追加 `writing_probe`。
- `PROFILE_DEFAULTS`（L36-46）追加三个探针字段默认值。
- `data/ai_settings.json` 自动持久化（复用现有 load/save 逻辑）。
- `GET/PUT /api/settings/ai` 自动包含新用途（无需改路由）。
- `POST /api/settings/ai/test` 自动支持测试（无需改路由）。

### 4.2 探针界面（抽屉新增 probe tab）

**位置**：`DrawerPanel.vue` 在 `analysis` 后新增第 10 个 tab `probe`。

**新建文件**：`lingshu-app/src/components/drawer/ProbeTab.vue`

**界面结构**（每章独立草稿，无历史）：

```
┌─ ProbeTab.vue ─────────────────────────────┐
│ [探针开关] [手动扫描本章节] [一键写回全部]  │
├─ 当前章节草稿 ─────────────────────────────│
│ 第19章 魔丸母女的操作依旧精彩               │
│ 最后扫描 16:42 · 字数 2286 · 草稿 3+1       │
│                                            │
│ ┌─ 概要草稿 ───────────────────────────┐  │
│ │ [AI 生成的章节概要文本，可编辑]       │  │
│ │ [采纳概要→写入章节 summary_text]     │  │
│ └──────────────────────────────────────┘  │
│                                            │
│ ┌─ 人物草稿（本章节）──────────────────┐  │
│ │ ☐ 叶岚月  对话模式  conf=0.65  [采纳]│  │
│ │ ☐ 周辉诚  动作模式  conf=0.60  [采纳]│  │
│ │ ☐ 枫母    动作模式  conf=0.60  [采纳]│  │
│ └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

**关键交互**：
- 切换章节 → ProbeTab 重新加载该章草稿（`GET /api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe/drafts`）。
- 单卡 `[采纳]` → 调用现有 `POST /api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback` 写回该人物到 characters 表。
- 概要 `[采纳概要]` → 调用新端点 `POST /api/workspace/chapters/{chapterId}/apply-summary` 写入 `chapters.summary_text`。
- `[一键写回全部]` → 调用新端点 `POST /api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe/writeback-all`，批量写回当前章节所有草稿（人物 + 概要）。
- 草稿可编辑（覆盖 AI 概要文本、修改人物名/role 后再采纳）。
- 已采纳的草稿标记为"已写回"状态，仍只在本章节视图内展示（不归档到历史）。

**草稿生命周期**（每章独立）：
- 写作触发扫描 → 同 entity_name 的新草稿替换旧草稿（取最新置信度），概要草稿覆盖旧概要。
- 点"采纳" → 写回正式库 + 该草稿标记 applied（仍留在本章节视图，状态变"已写回"）。
- 切换章节不丢失：草稿持久化在 analysis_cards 表，下次回到该章节仍可看到。

### 4.3 草稿存储

**复用 `analysis_cards` 表**，新增两个 `card_type`：

| card_type | writeback_target | 用途 |
|---|---|---|
| `writing_probe_summary` | `chapter_summary`（特殊：写 chapter.summary_text，不走 V3 writeback） | 章节概要草稿 |
| `writing_probe_character` | `character` | 章节人物草稿 |

**payload_json 字段映射**（人物草稿示例）：
```json
{
  "card_type": "writing_probe_character",
  "writeback_target": "character",
  "writeback_fields": { "name": "叶岚月", "role": "supporting", "profile_text": "..." },
  "evidence_quote": "原文证据...",
  "source_rule": "dialogue_pattern",
  "confidence": 0.65,
  "chapter_id": 146,
  "chapter_title": "第19章 魔丸母女的操作依旧精彩"
}
```

**payload_json 字段映射**（概要草稿示例）：
```json
{
  "card_type": "writing_probe_summary",
  "writeback_target": "chapter_summary",
  "writeback_fields": { "summary_text": "本章讲述了..." },
  "chapter_id": 146,
  "chapter_title": "第19章 魔丸母女的操作依旧精彩",
  "word_count": 2286
}
```

**run_id 处理**：探针草稿不依赖完整 V3 run。使用 book 维度的"探针伴随 run"：每书一个长期 run，`status='probe_companion'`，`pipeline_version='writing_probe_v1'`。首次触发时自动创建并缓存 run_id 到 `analysis_runs` 表。探针草稿的 `run_id` 字段指向该伴随 run。

### 4.4 探针触发机制

**前端**：`ContentEditor.vue` 监听章节内容变化，按配置 `interval_seconds`（默认 8 秒）防抖后调用 `POST /api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe`。

- 仅当 `writing_probe.enabled === true` 且当前在章节编辑模式时触发。
- 防抖：每次内容变化重置计时器，停止输入 8 秒后才调用。
- 手动触发：ProbeTab 的 `[手动扫描本章节]` 按钮立即调用同一端点（不受防抖限制）。
- 调用频率上限：每章每分钟最多 2 次自动扫描（防滥用）。

**后端流程**（新建 `novel_app/analysis/writing_probe.py`）：

```python
class WritingProbeService:
    def __init__(self, database: Database):
        self.database = database

    def scan_chapter(self, book_id: int, chapter_id: int) -> dict:
        """扫描章节，生成草稿写入 analysis_cards，返回新增草稿列表。"""
        # 1. 加载章节文本 + 元信息
        chapter = self.database.get_chapter(chapter_id)
        text = str(chapter["content"] or "")

        # 2. 获取或创建探针伴随 run
        run_id = self._ensure_companion_run(book_id)

        # 3. 用 MentionExtractor 扫描人物（复用刚优化的规则引擎）
        extractor = MentionExtractor.from_database(self.database, book_id)
        blocks = [{"block_uid": f"chapter-{chapter_id}", "text": text, "chapter_id": chapter_id}]
        mentions = extractor.extract_from_blocks(book_id=book_id, run_id=run_id, blocks=blocks)

        # 4. 过滤已有 characters，只保留新人物草稿
        existing_names = {normalize_entity_alias(c["name"]) for c in self.database.list_characters(book_id)}
        new_character_drafts = []
        for mention in mentions:
            if mention.entity_type != "character":
                continue
            if normalize_entity_alias(mention.normalized_text) in existing_names:
                continue
            if mention.confidence < self._threshold():
                continue
            new_character_drafts.append(self._upsert_character_draft(book_id, run_id, chapter_id, chapter, mention))

        # 5. 调 AI 生成章节概要（writing_probe purpose；AI 不可用时跳过概要，只保留人物草稿）
        summary_draft = None
        if self._ai_available():
            summary_text = self._generate_summary(book_id, chapter_id, text)
            if summary_text:
                summary_draft = self._upsert_summary_draft(book_id, run_id, chapter_id, chapter, summary_text)

        # 6. 审计日志
        self.database.create_audit_log(book_id, run_id=run_id, action="writing_probe_scan",
            target_type="chapter", target_uid=str(chapter_id),
            new_value={"character_drafts": len(new_character_drafts), "summary_draft": bool(summary_draft)},
            reason="writing probe companion scan")

        return {"character_drafts": new_character_drafts, "summary_draft": summary_draft}

    def _ensure_companion_run(self, book_id: int) -> int:
        """获取或创建 book 维度的探针伴随 run。"""
        # 查询 status='probe_companion' 的 run，没有则创建
        ...

    def _upsert_character_draft(self, ...):
        """写入/覆盖人物草稿到 analysis_cards（同 chapter + 同 name 覆盖）。"""
        # card_uid = f"probe-char-{chapter_id}-{normalize(name)}"
        # DELETE WHERE run_id=? AND card_uid=? 然后 INSERT（或 INSERT OR REPLACE）
        ...

    def _upsert_summary_draft(self, ...):
        """写入/覆盖概要草稿到 analysis_cards（同 chapter 覆盖）。"""
        # card_uid = f"probe-summary-{chapter_id}"
        ...
```

**新端点**（`lingshu_api/routers/workspace.py`）：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe` | 触发扫描，生成草稿 |
| GET | `/api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe/drafts` | 获取该章节所有草稿 |
| POST | `/api/workspace/books/{bookId}/chapters/{chapterId}/writing-probe/writeback-all` | 批量写回该章节所有草稿 |
| POST | `/api/workspace/chapters/{chapterId}/apply-summary` | 写入章节概要到 summary_text |

**概要写回特殊处理**：`writeback_target="chapter_summary"` 不走 V3 writeback（V3 只支持 character/world_entry/book），由 `apply-summary` 端点直接 `UPDATE chapters SET summary_text=? WHERE id=?`，但仍创建 snapshot（记录旧 summary_text）+ 审计日志。

### 4.5 一键写回（复用 V3 writeback）

**人物草稿写回**：复用现有 `POST /api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback`：
1. 后端 `store.apply_card()` → `writeback_v3_card()`：
   - schema gate 校验 name 字段
   - 创建 `analysis_apply_snapshots` 快照（含 before_state）
   - 写入 characters 表（新建或合并；`writeback_to_state_machine` + `merge_character_profile_supplement`）
   - 标记 card status='applied'
2. WebSocket 广播 `analysis_v3.writeback_completed`
3. 前端刷新人物面板（emit `lingshu:characters-updated`）

**批量写回**（`writeback-all` 端点）：循环调用 `apply_card`，返回聚合结果（成功数/失败数/失败详情）。限流 3/min。

**概要写回**（`apply-summary` 端点）：
1. 读取草稿 payload 的 `writeback_fields.summary_text`
2. 创建 snapshot（记录旧 summary_text）
3. `UPDATE chapters SET summary_text=? WHERE id=?`
4. 标记概要草稿 status='applied'
5. 审计日志

**与证据门禁关系**：
- 草稿进 analysis_cards = 通过证据门禁的"草案"级（已有 evidence_quote）
- 用户点"采纳/一键写回" = 人工审核确认 = 升级为 trusted
- 完全符合项目硬约束"分析草案须经证据门禁"，不破坏现有规则。

### 4.6 人物 tab 章节过滤

**位置**：`CharactersTab.vue`（当前只按 bookId 加载全书人物，无章节感知）。

**触发**：直接读 `bookStore.activeChapterId`（`lingshu-app/src/stores/book.js` L24），改动最小。

**界面行为**：
- 进入章节 → CharactersTab 顶部显示"当前章节: 第N章 标题" + `[切到全书]` 按钮，列表展示本章出场人物（按出现次数降序）。
- `[切到全书]` 按钮 → 回退到原全书人物列表。
- 退出章节（切到书/卷）→ 自动回退全书列表。
- 本章出场人物点击仍可打开详情弹窗（复用现有 `onSelect`）。

**后端新端点**：`GET /api/workspace/books/{bookId}/chapters/{chapterId}/appearing-characters`

**实现逻辑**（复用 MentionExtractor）：
1. `MentionExtractor.from_database(db, book_id)` —— 加载所有 characters 作为种子（`formal_character` 置信度 0.95）。
2. 加载章节文本，扫描提取 mention。
3. 过滤 `entity_type == 'character'` 且 `source_rule == 'formal_character'`。
4. 按 `normalized_text` 聚合，统计每人物出现次数 + 最高置信度。
5. 与 characters 表 join 返回完整人物信息。
6. 返回 `[{character_id, name, role, profile_text, appear_count, max_confidence}]`，按 appear_count 降序。

**规则匹配说明**：用 characters 表所有人物名作为种子，对当前章节做规则匹配。与探针草稿（发现"新"人物）互补：本章过滤找"已有"人物，探针找"漏抽"人物。两者共用 MentionExtractor 扫描逻辑，但用途不同。

## 5. 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `lingshu-app/src/components/settings/AiSettingsSection.vue` | 修改 | 新增 writing_probe 用途配置面板 |
| `lingshu_api/services/ai_settings.py` | 修改 | AI_PURPOSES 追加 writing_probe + PROFILE_DEFAULTS 扩展 |
| `lingshu-app/src/components/drawer/DrawerPanel.vue` | 修改 | 新增 probe tab |
| `lingshu-app/src/components/drawer/ProbeTab.vue` | **新建** | 探针界面（每章独立草稿） |
| `lingshu-app/src/components/workspace/ContentEditor.vue` | 修改 | 8 秒防抖轮询触发 |
| `lingshu_api/routers/workspace.py` | 修改 | 新增 writing-probe / drafts / writeback-all / apply-summary / appearing-characters 端点 |
| `novel_app/analysis/writing_probe.py` | **新建** | 探针服务：扫描 + 草稿生成 + 伴随 run 管理 + 概要生成 |
| `lingshu-app/src/components/drawer/CharactersTab.vue` | 修改 | 章节人物过滤视图 |
| `lingshu-app/src/stores/character.js` | 修改 | 新增 fetchAppearingCharacters(bookId, chapterId) |

## 6. 安全与合规

- 探针扫描不自动写回正式库，所有写回需用户手动点击（符合证据门禁硬约束）。
- 写回前创建 snapshot（analysis_apply_snapshots），支持回滚。
- 写回操作记录审计日志（action=`writing_probe_writeback` / `writing_probe_summary_apply`）。
- 探针 AI 调用复用 `require_ai_access` 装饰器（符合"All AI capabilities must require login"硬约束）。
- 探针扫描频率上限：每章每分钟最多 2 次自动扫描，防止 API 滥用。
- API key 加密存储（复用 `protect_secret`）。

## 7. 测试策略

- **单元测试**：
  - `WritingProbeService.scan_chapter`：给定章节文本，验证草稿生成正确（人物 + 概要）。
  - `WritingProbeService._ensure_companion_run`：验证伴随 run 创建/复用。
  - `WritingProbeService._upsert_character_draft`：验证同 chapter + 同 name 覆盖。
  - 章节人物过滤：给定章节文本 + 现有 characters，验证按出现次数排序。
- **集成测试**：
  - 端到端：触发扫描 → 草稿入表 → 采纳写回 → characters 表更新。
  - 批量写回：多草稿一次性写回，验证 snapshot + 审计日志。
  - 概要写回：写入 chapters.summary_text + snapshot。
- **前端测试**：
  - ProbeTab 切章重新加载草稿。
  - CharactersTab 章节过滤视图切换。
  - ContentEditor 防抖触发（8 秒后调用，期间不调用）。

## 8. 未决事项

无。所有关键决策点已在设计确认中明确。
