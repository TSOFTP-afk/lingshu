# 灵枢数据库更改记录

> 本文档记录 hybrid-database-architecture spec 实施过程中所有数据库相关更改。
> 实施时间：2026-07-02 ~ 2026-07-03
> Spec 文档：[.trae/specs/hybrid-database-architecture/](.trae/specs/hybrid-database-architecture/)

---

## 一、SQLite FTS5 全文检索（Task 1）

**目标**：为章节标题与正文提供毫秒级中文全文检索，替代旧的逐章 `str.find` 扫描。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/schema.py](novel_app/db/schema.py) | 修改 | 新增 `FTS5_CHAPTERS_MIGRATION_ID = "fts5_chapters_v2"` + `_apply_fts5_chapters_migration()` 方法（第 1381 行），创建 `chapters_fts` 虚拟表 + INSERT/UPDATE/DELETE 触发器 |
| [novel_app/database.py](novel_app/database.py) | 修改 | 注册 `cjk_unigram` 函数（第 178 行 `raw_connection.create_function("cjk_unigram", 1, cjk_unigram)`），解决中文分词问题 |
| [lingshu_api/services/db_bridge.py](lingshu_api/services/db_bridge.py) | 修改 | 重写 `search_book` 方法，新增 `_fts5_available` / `_search_book_fts5` / `_search_book_legacy` 三方法，FTS5 不可用时降级为旧扫描 |

### 关键设计

- **中文分词**：用 `cjk_unigram` 函数将 CJK 字符按单字切分（替代原 tokenchars 方案），FTS5 触发器存储时与查询时均经过此函数处理
- **短语搜索**：查询串经 `cjk_unigram` 后用双引号包裹作为 FTS5 phrase（`"白 狐"` 要求两 token 相邻），避免 AND/OR/NOT 关键字干扰
- **bm25 排序**：用 `bm25(chapters_fts)` 评分函数按相关性排序
- **降级路径**：`_fts5_available` 检测 `chapters_fts` 虚拟表是否存在，不存在时走 `_search_book_legacy` 逐章扫描

---

## 二、HNSW 向量存储（Task 2 + Task 3）

**目标**：用本地 HNSW 索引替代 Qdrant，支持 RAG 检索与分析向量存储，无需外部服务。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/hnsw_store.py](novel_app/db/hnsw_store.py) | 新建（472 行） | `HNSWStore` 核心：faiss IndexHNSWFlat + IndexIDMap2，SQLite 持久化 |
| [novel_app/db/schema.py](novel_app/db/schema.py) | 修改 | 新增 `HNSW_VECTORS_MIGRATION_ID = "hnsw_vectors_v1"` + `_apply_hnsw_vectors_migration()`（第 1495 行），创建 `vectors` 表 |
| [novel_app/analysis/vector_store.py](novel_app/analysis/vector_store.py) | 修改 | `AnalysisVectorStore` 改用 `HNSWStore`（import + 构造函数增加可选 `db_path` 参数） |
| [novel_app/rag/retriever.py](novel_app/rag/retriever.py) | 修改 | `ChapterRetriever` 改用 `HNSWStore`（import + 构造函数增加可选 `db_path` 参数） |
| [novel_app/rag/qdrant_client.py](novel_app/rag/qdrant_client.py) | 修改 | 添加模块级 `warnings.warn(DeprecationWarning)` + 类 docstring 标注 `[DEPRECATED]` |
| [requirements.txt](requirements.txt) | 修改 | 注释掉 qdrant-client/protobuf，新增 `faiss-cpu>=1.14,<2` + `numpy>=2.0,<3` |

### 关键设计

- **ANN 库选择**：faiss-cpu 替代 hnswlib（Python 3.13 + Windows 无预编译 wheel），`IndexHNSWFlat` 算法等价且有预编译 wheel
- **延迟重建策略**：因 faiss HNSW 不支持 `remove_ids`，upsert/delete 仅写 SQLite + 标记 `dirty`，search 时 `_rebuild_if_dirty` 全量重建 faiss 索引
- **cosine 相似度**：向量归一化后用 `METRIC_INNER_PRODUCT`，返回的 distance 即 cosine 相似度
- **filter_condition 过采样**：faiss 不支持原生过滤，search `limit*10` 个结果后在 Python 层过滤
- **point_id 类型还原**：SQLite 存 TEXT，`_restore_point_id_type` 尝试还原为 int
- **参数**：`m=32, ef_construction=40, ef_search=64`

---

## 三、Redis 缓存层（Task 4）

**目标**：为高频读路径（书籍树/章节/分析状态/书籍列表）添加 Redis 缓存，减少 SQLite 读压力；提供分布式锁防止书籍分析并发冲突。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/redis_client.py](novel_app/db/redis_client.py) | 新建（137 行） | Redis 客户端单例 + 优雅降级 + 健康检查 |
| [novel_app/db/cache.py](novel_app/db/cache.py) | 新建（274 行） | `CacheManager` 类：4 类缓存 + 分布式锁 + 批量失效 |
| [lingshu_api/services/db_bridge.py](lingshu_api/services/db_bridge.py) | 修改 | 读路径加缓存回源，写路径加缓存失效（书籍/分卷/章节共 16 个方法） |
| [lingshu_api/main.py](lingshu_api/main.py) | 修改 | `/api/health` 和 `/api/v1/health` 添加 `redis` 字段（延迟导入 `ping_redis`） |
| [docker-compose.yml](docker-compose.yml) | 新建 | redis:7-alpine 服务配置（AOF 持久化 + 256mb LRU + 健康检查 + 密码保护） |
| [requirements.txt](requirements.txt) | 修改 | 新增 `redis[hiredis]>=5.0.0,<9` |

### 关键设计

- **优雅降级**：Redis 不可用时 `redis_client` 返回 None，`CacheManager` 所有方法返回 None/False/0 不抛异常，业务逻辑不受影响
- **单例模式**：`get_redis_client()` 全局共享连接池，首次连接失败缓存 None 避免重复尝试
- **4 类缓存**：
  - 书籍树 `book_tree:{book_id}` TTL=300s
  - 章节 `chapter:{chapter_id}` TTL=600s
  - 分析运行 `analysis_run:{run_id}` TTL=60s
  - 书籍列表 `book_list:{user_id}` TTL=300s
- **分布式锁**：`SET NX EX` 获取（返回 token）+ Lua 脚本释放（token 匹配才删除），TTL=3600s；无 Redis 时返回伪 token `"nolock:..."` 允许单机无锁运行
- **SCAN 分批扫描**：`_delete_pattern` 用 SCAN 避免 KEYS 阻塞
- **缓存回源**：`get_or_set(key, ttl, loader)` 未命中时调 loader 并回填；无 Redis 时直接回源
- **批量失效**：
  - `invalidate_on_book_write(book_id)`：失效 book_tree + book_list:*
  - `invalidate_on_chapter_write(book_id, chapter_id)`：失效 chapter + book_tree
  - `invalidate_on_book_delete(book_id)`：失效 book_tree + book_list:*
- **db_bridge.py 改动方法清单**：
  - 书籍：`list_books` / `create_book` / `get_book` / `rename_book` / `delete_book` / `update_book_outline` / `update_book_world`
  - 分卷：`create_volume` / `rename_volume` / `delete_volume` / `reorder_volumes`
  - 章节：`create_chapter` / `get_chapter` / `update_chapter` / `delete_chapter` / `move_chapter`
- **桌面端**：Electron 打包不依赖 Redis，通过优雅降级处理；如需启用设置 `REDIS_URL` 环境变量即可

---

## 四、写操作批量化（Task 5）

**目标**：将分析写回场景的逐条 INSERT/UPDATE 改为批量操作，减少 SQLite commit 次数与锁竞争。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/analysis.py](novel_app/db/analysis.py) | 修改 | 新增 5 个 batch 方法（第 1828-1985 行） |
| [novel_app/analysis/pipeline_v3.py](novel_app/analysis/pipeline_v3.py) | 修改 | `_auto_writeback_high_confidence_cards` 用 `transaction()` 包裹循环，抑制内层 commit |

### 新增方法

1. `create_analysis_cards_batch`（第 1828 行）— 批量插入分析卡片
2. `mark_analysis_cards_applied_batch`（第 1867 行）— 批量标记卡片已应用
3. `update_analysis_card_payloads_batch`（第 1900 行）— 批量更新卡片 payload
4. `create_analysis_apply_snapshots_batch`（第 1930 行）— 批量创建应用快照
5. `create_analysis_audit_logs_batch`（第 1959 行）— 批量创建审计日志

### 关键设计

- 实际改动在 `pipeline_v3.py` 的 `_auto_writeback_high_confidence_cards` 用 `transaction()` 包裹循环，抑制内层 `apply_card` 的 commit，整批作为一个事务提交
- 遵循 project_memory 硬约束：writeback 必须用 `Database.transaction()` 上下文管理器防止部分写入

---

## 五、离线变更追踪（Task 6）

**目标**：记录所有写操作的变更日志，为增量同步引擎（Task 7）提供数据源。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/schema.py](novel_app/db/schema.py) | 修改 | 新增 `SYNC_CHANGELOG_MIGRATION_ID = "sync_changelog_v1"` + `_apply_sync_changelog_migration()`（第 1458 行），创建 `sync_changelog` 表 + `sync_meta` 表 |
| [novel_app/db/sync_changelog.py](novel_app/db/sync_changelog.py) | 新建（176 行） | `SyncChangelogMixin` 类：`log_change` / `get_pending_changes` / `mark_synced` / `get_sync_cursor` / `set_sync_cursor` |
| [novel_app/database.py](novel_app/database.py) | 修改 | 注册 `SyncChangelogMixin`（第 137 行）到 Database 继承链 |
| [novel_app/db/library.py](novel_app/db/library.py) | 修改 | 7 个写方法注入 `log_change` 调用 |

### library.py 注入点（7 处）

| 行号 | 方法 | 操作类型 |
|---|---|---|
| 59 | `create_book` | insert |
| 96 | `rename_book` | update |
| 178 | `delete_book` | delete |
| 364 | `create_chapter` | insert |
| 406 | `rename_chapter` | update |
| 426 | `delete_chapter` | delete |
| 459 | `update_chapter_volume`（move） | update |

### 关键设计

- `sync_changelog` 表记录：`table_name` / `record_id` / `operation`（insert/update/delete）/ `payload_json` / `created_at` / `synced_at`
- `sync_meta` 表存储同步游标（`last_synced_csid`）
- `log_change` 在写操作同一事务内记录，保证变更不丢失

---

## 六、增量同步引擎（Task 7）

**目标**：基于 sync_changelog 实现本地↔云端增量同步，支持离线写作后自动合并。

### 改动文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| [novel_app/db/sync_engine.py](novel_app/db/sync_engine.py) | 新建（485 行） | `SyncEngine` 完整实现 |

### 核心能力

- `push_incremental()` — 批量推送 sync_changelog via POST `/api/sync/push`
- `pull_incremental()` — 拉取云端变更，直接 SQL 写入避免同步循环
- `Last-Write-Wins` 冲突解决（UTC 时间戳感知）
- 自动同步：`threading.Timer` 守护线程（5 秒间隔，RLock 防重入死锁，`online=False` 时 ConnectError 暂停）
- SQL 注入防护：白名单 14 表 + 列校验

### 修复的 Bug

1. `sync_meta` 创建时机（首次同步前确保存在）
2. SQLite naive vs ISO aware 时区比较
3. Timer Lock 死锁 → 改用 RLock

---

## 七、迁移注册顺序

所有迁移在 [novel_app/db/schema.py](novel_app/db/schema.py) 的 `_apply_app_migrations`（第 1534 行）中按顺序注册：

```
_apply_analysis_v3_foundation_migration()      # 第 1543 行
STRUCTURED_TEMPLATE_MIGRATION_ID               # 第 1544-1563 行
_apply_character_state_machine_migration()     # 第 1564 行
_apply_character_state_machine_static_attrs_migration()
_apply_chapter_generation_snapshot_migration()
COMMUNITY_CARD_POSTS_MIGRATION_ID
_apply_fts5_chapters_migration()               # 第 1630 行  ← Task 1
_apply_sync_changelog_migration()              # 第 1631 行  ← Task 6
_apply_hnsw_vectors_migration()                # 第 1632 行  ← Task 2+3
```

### 迁移 ID 清单

| 迁移 ID | 任务 | 说明 |
|---|---|---|
| `fts5_chapters_v2` | Task 1 | FTS5 全文检索虚拟表 + 触发器 |
| `sync_changelog_v1` | Task 6 | 离线变更追踪表 + 同步游标表 |
| `hnsw_vectors_v1` | Task 2+3 | HNSW 向量存储表 |

---

## 八、依赖变更（requirements.txt）

| 依赖 | 版本 | 用途 | 状态 |
|---|---|---|---|
| `faiss-cpu` | `>=1.14,<2` | HNSW 向量索引（替代 qdrant-client） | 新增 |
| `numpy` | `>=2.0,<3` | faiss 依赖，向量矩阵化计算 | 新增 |
| `redis[hiredis]` | `>=5.0.0,<9` | Redis 缓存层 + 分布式锁 | 新增 |
| `qdrant-client` | — | 旧向量客户端 | 已注释（废弃） |
| `protobuf` | — | qdrant 依赖 | 已注释（不再需要） |

---

## 九、冒烟测试验证

### HNSW 向量存储（Task 2+3）
- 5 项测试通过：HNSWStore basic / int point_id / persistence / AnalysisVectorStore 集成 / ChapterRetriever 集成
- 待验证：索引恢复时间 ≤ 2s（50000 向量）、相似度检索延迟 ≤ 10ms（≤ 50000 向量）

### Redis 缓存层（Task 4）
- 4 项测试通过（无 Redis 环境验证优雅降级）：
  1. `redis_client` 降级行为（`is_redis_available=False`, `ping=down`）
  2. `CacheManager` 全方法降级正常 + 分布式锁伪 token + `get_or_set` 正确回源
  3. `WorkspaceDB` 完整 CRUD 流程正常（创建书→分卷→章节→读取→更新→移动→删除）
  4. 重复读取幂等性

### FTS5 全文检索（Task 1）
- 中文搜索、sync_changelog 记录与同步标记、批量写入等核心功能通过

---

## 十、待办任务（spec 中剩余）

| 任务 | 说明 | 依赖 |
|---|---|---|
| Task 8 | 云 API 端点 | 依赖 PostgreSQL 部署 |
| Task 9 | 云端 PostgreSQL + pgvector | — |
| Task 10 | 云端同步后端 | 依赖 Task 9 |
| Task 11 | 前端同步交互 | 依赖 Task 8 |
| Task 12 | 数据迁移脚本 | 依赖 Task 2 |
| Task 13 | 集成测试 + 性能基准 | 依赖 Task 1/3/4/5/7 |

---

## 附：数据库文件布局

```
data/
├── novels.db              # 主数据库（书籍/章节/人物/分析等）
├── bookstore_demo.db      # 书店演示数据库
└── vectors.db             # HNSW 向量数据库（Task 2+3）

# Redis（Task 4，可选）
# 桌面端：不依赖，优雅降级
# 云端：docker-compose.yml 启动 redis:7-alpine 容器
```
