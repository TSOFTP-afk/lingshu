# AnalysisTab.vue 分段地图（拆解前施工图）

> 源文件：`src/components/drawer/AnalysisTab.vue`（2931 行）
> 模板 1-1322，`<script setup>` 1324-2572，样式 2574-2931。
> 行号均为源文件行号，以当前 git 工作区版本为准（拆解前快照）。
> 定性测试：`tests/unit/components/AnalysisTab.spec.js`（行为锁定）。

## 0. 对外契约（模板/父组件视角）

AnalysisTab **没有 props、没有 emits（defineProps/defineEmits/defineExpose 均不存在）**。
父组件 `src/components/drawer/DrawerPanel.vue` 的使用方式极简：

- L103 `import AnalysisTab from './AnalysisTab.vue'`；L53 直接放在 `<el-tab-pane name="analysis">` 里：`<AnalysisTab />`，不传任何 prop、不监听任何事件。
- DrawerPanel 通过 `localStorage('lingshu_drawer_active_tab')` 记忆激活 tab；左侧选中节点类型为 `chapter` 时自动切到 `analysis`（DrawerPanel L134-145）。
- 与外界的全部交互走 **eventBus**（`src/composables/useEventBus.js`，模块级 Map，非 pinia）：

| 方向 | 事件 | 说明 |
| --- | --- | --- |
| 监听 | `lingshu:book-analysis-start` | 外部触发"开始分析"：onBookAnalysisStart（1590-1601）按 analysisMode 分发 createV3Run / createV1OneShotRun |
| 发出 | `lingshu:drawer-tab` | onBookAnalysisStart 把抽屉切到 analysis 页（DrawerPanel 监听） |
| 发出 | `lingshu:characters-updated` | V1 写回（1837）、实体审核写回（2146）、卡片写回（2432）、WS 批量写回（2533） |
| 发出 | `lingshu:world-updated` | 同上（1838/2148/2434/2534） |
| 发出 | `lingshu:book-updated` | V1 写回（1839）、WS 批量写回（2535） |
| 发出 | `lingshu:writeback-completed` | 实体审核（2150）、卡片写回（2438）、WS 写回广播（2537） |

- 依赖的 store：`useBookStore`（只读 `currentBookId`，L1338）、`useAuthStore`（`requireAiAccess`，内含 `isLoggedIn` 判定 + 发 `lingshu:open-login`）、`useWsStore`（`connect/disconnect/connections`）。
- localStorage：`lingshu_active_probes_<bookId>`（主动探针历史，2058-2074）。

## 1. WebSocket 连接与 eventBus（拆解时建议整块保留在主组件或独立 composable）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `WS_PATH_ANALYSIS_V3 = '/ws/analysis-v3'` | 1341 | V3 专用 |
| `_wsMessageHandler`（模块内 let） | 1342 | 仅 WS 域 |
| `onMounted`（注册 eventBus + loadWorkspaceSettings + loadV3Runs + loadV1Runs + _setupWsListener） | 2506-2513 | 共享，留在主组件 |
| `onUnmounted`（off + _teardownWsListener） | 2515-2518 | 共享，留在主组件 |
| `_setupWsListener` | 2520-2560 | WS 域；调用 wsStore.connect（store 内部会 new WebSocket 并在 onopen 时 sendWsAuth 发 `{type:'auth', payload:{token}}`） |
| `_teardownWsListener` | 2562-2571 | WS 域；移除 listener + wsStore.disconnect |
| `watch(bookId)`（清空全部 V1/V3 状态 + loadActiveProbeHistory + loadV3Runs + loadV1Runs） | 2466-2487 | 共享，留在主组件 |

**连接建立时机**：挂载即连（onMounted → `_setupWsListener` → `wsStore.connect('/ws/analysis-v3')`）。鉴权帧由 wsStore（`src/stores/websocket.js` connect 的 onopen）通过 `sendWsAuth` 发送，格式 `{"type":"auth","payload":{"token":<token>}}`（`src/utils/api.ts` 209-215）。

**监听的消息类型**：只处理 `analysis_v3.writeback_completed`（2527）；忽略其他类型与 JSON 解析失败；`payload.bookId` 与当前 bookId 不符时忽略（2530）。
**eventBus 转发**：`payload.batch=true` → 依次 emit `lingshu:characters-updated` / `lingshu:world-updated` / `lingshu:book-updated`（source:'ws_writeback'）；总是 emit `lingshu:writeback-completed`（writebackTarget 按 applied_table 映射 characters→character / world_entries→world_entry / books→book，batch 时为 undefined）；若 `payload.run_id` 且当前有选中 run → 重新拉 diagnostics + runs（2550-2553）。

另一条**临时 WS**：`runV3AnalysisOverWs`（1632-1716）在"开始分析"时新建一次性连接：onopen 发 auth（1663），收到 `auth_ok` 后发 `analyze_v3`（task_id=`analysis-v3-<ts>`，payload 含 book_id/use_ai，1678-1687），处理 `ping`(回 pong)、`analysis_v3.progress`、`analysis_v3.result`（cancelled 视为失败）、`analysis_v3.error`；带 30 分钟超时定时器 + 60 秒无进度 stall 检查器（1639-1646）。

## 2. 设置读写

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `workspaceSettings` | 1344 | 设置域 |
| `loadingWorkspaceSettings` | 1345 | 设置域 |
| `savingWorkspaceSettings` | 1346 | 设置域 |
| `loadWorkspaceSettings`（GET /settings/workspace） | 1603-1615 | 挂载时调用（2510） |
| `saveWorkspaceSettings`（PUT /settings/workspace） | 1617-1630 | **模板中无任何引用（当前是死代码/预留），拆解时可删除或留待恢复** |

注意：`analysis_pipeline_mode` 只被读写，不影响本组件任何渲染分支。

## 3. V3 运行记录（runs）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `creatingV3Run` | 1347 | V3 |
| `analysisV3Progress` | 1348 | V3 |
| `runningIncrementalV3Run` | 1349 | V3 |
| `useAiAnalysis` | 1350 | V3（createV3Run / incremental 共用） |
| `loadingV3Runs` | 1353 | V3 |
| `selectedV3RunId` | 1380 | **共享（几乎全部 V3 域都以它为键）** |
| `analysisV3WorkflowTab` | 1381 | V3（jumpToBlock 2408 也写它） |
| `selectedV3Run` computed | 1421 | **共享（模板多处 + 诊断域）** |
| `runStatusText` + `RUN_STATUS_TEXT` | 1424-1434 | **共享，V1/V3 模板都用** |
| `createV3Run` | 1718-1746 | V3（走 WS） |
| `createIncrementalV3Run`（POST …/analysis-v3/incremental） | 1748-1765 | V3 |
| `loadV3Runs`（GET …/books/{id}/analysis-v3/runs） | 1860-1873 | **共享（被 watch bookId、onMounted、runMemoryLayer、runProbes、markEntityReviewed、execute/cancelBacktrackTask、writebackCard、WS 回调调用）** |
| `loadV3RunDiagnostics`（并行拉 10 类诊断） | 1875-1892 | **共享（诊断域的调度中枢）** |

阶段条（仅渲染用）：`DEFAULT_V3_STAGES` 1436-1448、`normalizeV3Stages` 1450-1457、`currentV3StageIndexForRun` 1459-1476、`currentV3StageTextForRun` 1478-1482、`currentV3StageIndex` 1484、`currentV3StageText` 1486、`v3StageItems` 1488-1495。

## 4. V3 运行明细（blocks/mentions/entities/facts/cards/events）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `loadingV3Blocks` / `analysisV3Blocks` | 1354 / 1366 | blocks 域（v3OverviewItems 1549 也读） |
| `loadingV3Mentions` / `analysisV3Mentions` | 1355 / 1367 | mentions 域（splitMentionOptions 1507 读） |
| `loadingV3Entities` / `analysisV3Entities` | 1356 / 1368 | **共享（实体审核域读写、entityOptions/findEntity）** |
| `loadingV3Facts` / `analysisV3Facts` | 1357 / 1369 | facts 域（splitFactOptions 1512 读） |
| `loadingV3Cards` / `analysisV3Cards` | 1358 / 1370 | cards 域 |
| `loadingV3Events` / `analysisV3Events` | 1359 / 1371 | events 域 |
| `loadV3Blocks`（GET …/runs/{id}/blocks） | 1894-1906 | blocks |
| `loadV3Mentions`（…/mentions） | 1908-1920 | mentions |
| `loadV3Entities`（…/entities） | 1922-1934 | **共享（实体审核域）** |
| `loadV3Facts`（…/facts） | 1936-1948 | facts |
| `loadV3Cards`（…/cards） | 1950-1962 | cards |
| `loadV3Events`（…/events） | 1964-1976 | events |

模式（M0-M8 记忆分层/卡片步骤按钮）：`runningMemoryLayer` 1351、`runMemoryLayer`（POST …/steps/memory_layer）1978-1991；`runningProbes` 1352、`runProbes`（POST …/steps/probes）1993-2006。

## 5. 探针（probes：文章探针 plans/results + 主动探针）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `loadingV3ProbePlans` / `analysisV3ProbePlans` | 1360 / 1372 | 探针 |
| `loadingV3ProbeResults` / `analysisV3ProbeResults` | 1361 / 1373 | 探针（v3OverviewItems 1554 也读） |
| `activeProbeQuery` / `activeProbeLoading` / `activeProbeResults` | 1374-1376 | 主动探针 |
| `probeConflictResults` / `probeManualReviewCount` | 1560-1564 | **共享（v3OverviewItems 1555 读 manualReviewCount）** |
| `activeProbeResultsOnly` / `activeProbePlansOnly` | 1566-1571 | 探针 |
| `loadV3ProbePlans`（…/probes/plans） | 2008-2020 | 探针 |
| `loadV3ProbeResults`（…/probes/results） | 2022-2034 | 探针 |
| `runActiveProbe`（POST …/books/{id}/active-probe） | 2036-2056 | 主动探针 |
| `saveActiveProbeHistory`（localStorage） | 2058-2065 | 主动探针 |
| `loadActiveProbeHistory`（localStorage，watch bookId 2484 调用） | 2067-2074 | 主动探针 |

## 6. 回溯（backtrack）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `loadingV3BacktrackTasks` / `analysisV3BacktrackTasks` | 1362 / 1377 | 回溯（v3OverviewItems 1556 读） |
| `creatingBacktrackEntityUid` | 1382 | 回溯 |
| `executingBacktrackTaskId` / `cancellingBacktrackTaskId` | 1383-1384 | 回溯 |
| `loadV3BacktrackTasks`（…/backtrack/tasks） | 2076-2088 | 回溯 |
| `createEntityBacktrackTask`（POST …/backtrack/tasks） | 2105-2123 | 回溯（实体审核面板触发） |
| `executeBacktrackTask`（POST …/backtrack/tasks/{id}/execute） | 2261-2276 | 回溯 |
| `cancelBacktrackTask`（POST …/backtrack/tasks/{id}/cancel） | 2278-2293 | 回溯 |
| `canCancelBacktrackTask` | 2349-2351 | 回溯 |

## 7. 实体审核（review/merge/split/rollback）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `loadingV3Review` / `analysisV3Review` | 1363 / 1378 | 审核（v3OverviewItems 不读，模板概览页读） |
| `loadingEntityVersions` / `entityVersionsForReview` | 1364 / 1379 | 审核（rollbackVersionOptions 1519 读） |
| `reviewingEntityUid` / `runningEntityReviewAction` | 1385-1386 | 审核 |
| `entityMergeForm` | 1387-1392 | 审核 |
| `entitySplitForm` | 1393-1398 | 审核 |
| `entityRollbackForm` | 1399-1402 | 审核 |
| `entityOptions` / `activeEntityOptions` / `mergeSourceOptions` | 1497-1505 | 审核 |
| `splitMentionOptions` / `splitFactOptions` / `rollbackVersionOptions` | 1507-1522 | 审核 |
| `canMergeEntities` / `canSplitEntity` / `canRollbackEntity` | 1524-1537 | 审核 |
| `loadV3Review`（GET …/review） | 2090-2103 | 审核 |
| `markEntityReviewed`（PATCH …/entities/{uid}，写回后 emit 事件） | 2125-2161 | 审核（依赖 loadV3RunDiagnostics/loadV3Runs） |
| `loadEntityVersionsForReview`（GET …/entities/{uid}/versions） | 2163-2175 | 审核 |
| `mergeEntities`（POST …/entities/merge） | 2177-2207 | 审核 |
| `splitEntity`（POST …/entities/{uid}/split） | 2209-2235 | 审核 |
| `rollbackEntity`（POST …/entities/{uid}/versions/{v}/rollback） | 2237-2259 | 审核 |
| `resetEntityReviewForms` | 2329-2347 | **共享（createV3Run、loadV3RunDiagnostics、watch bookId 调用）** |
| `findEntity` / `mentionsForEntity` | 2314-2320 | **共享（表单 options 与审核动作都用）** |
| watch(entityRollbackForm.entityUid) | 2489-2495 | 审核 |
| watch(entitySplitForm.sourceUid) | 2497-2500 | 审核 |
| watch(entityMergeForm.targetUid) | 2502-2504 | 审核 |

## 8. 写回（V3 卡片写回）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `cardDetailVisible` / `cardDetailCard` | 1403-1404 | 写回（卡片详情对话框 1002-1230） |
| `writingBackCardUid` | 1405 | 写回 |
| `canWritebackCard` | 1539-1544 | 写回 |
| `openCardDetail` | 2375-2378 | 写回 |
| `writebackCard`（POST …/cards/{uid}/writeback，emit 3 类刷新事件 + writeback-completed） | 2414-2451 | 写回 |
| `cardStatusTagType` | 2380-2385 | **共享，V1 模板也用** |
| `writebackTargetLabel` / `writebackFieldLabel` | 2387-2406 | 写回 |
| `jumpToBlock` | 2408-2412 | 写回（写 analysisV3WorkflowTab，跨到 V3 域） |

## 9. V1 一次性管线（legacy）

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `analysisMode` / `analysisModeOptions` | 1406-1410 | **共享（模式切换开关，V1/V3 渲染总开关）** |
| `onBookAnalysisStart`（eventBus 入口，按 mode 分发） | 1590-1601 | **共享，留在主组件** |
| `creatingV1OneShotRun` | 1411 | V1 |
| `loadingV1Runs` / `loadingV1Cards` | 1412-1413 | V1 |
| `analysisV1Runs` / `analysisV1Cards` | 1414-1415 | V1 |
| `selectedV1RunId` | 1416 | V1 |
| `v1CardDetailVisible` / `v1CardDetailCard` | 1417-1418 | V1（对话框 1233-1320） |
| `applyingV1Run` | 1419 | V1 |
| `selectedV1Run` computed | 1422 | V1 |
| `createV1OneShotRun`（POST …/books/{id}/analysis-v1/one-shot） | 1767-1783 | V1 |
| `loadV1Runs`（GET …/books/{id}/analysis/runs） | 1785-1798 | V1 |
| `loadV1RunCards`（GET /workspace/analysis/runs/{id}/cards） | 1800-1812 | V1 |
| `openV1CardDetail` | 1814-1817 | V1 |
| `applyV1Run`（POST /workspace/analysis/runs/{id}/apply，409 弱证据二次确认，emit 3 类刷新事件） | 1819-1858 | V1 |

## 10. 其他 / 共享工具函数

| 条目 | 行号 | 共享情况 |
| --- | --- | --- |
| `bookId` computed | 1338 | **共享，留在主组件** |
| `v3OverviewItems` | 1546-1558 | **共享（读 runs/blocks/entities/facts/cards/probeResults/backtrackTasks/probeManualReviewCount）** |
| `selectedV3RunDiagnostics` | 1573-1588 | 共享（"复制诊断"按钮 + copyDiagnostics） |
| `confirmV3Action`（ElMessageBox.confirm 封装） | 2453-2464 | **共享（所有 V3 危险操作 + applyV1Run）** |
| `errorMessage` | 2295-2300 | **共享（V1/V3 错误解析）** |
| `shortHash` / `confidenceText` / `entityLabel` / `splitCsv` | 2302-2327 | 共享（entityLabel 被 entityOptions 用；confidenceText 被 V1 模板用） |
| `copyDiagnostics`（clipboard 兜底） | 2353-2373 | 共享（5 处模板按钮） |

## 11. 挂载时初始 API 调用清单（行为锁定的最硬校验）

`bookStore.currentBookId` 有值时，onMounted（2506-2513）+ 链式加载产生（loadV3Runs 自动选中第一个 run → loadV3RunDiagnostics 并行 10 个请求；loadV1Runs 自动选中第一个 run → loadV1RunCards）：

1. `GET /settings/workspace`（loadWorkspaceSettings）
2. `GET /workspace/books/{id}/analysis-v3/runs`
3. `GET /workspace/analysis-v3/runs/{runId}/blocks`
4. `GET /workspace/analysis-v3/runs/{runId}/mentions`
5. `GET /workspace/analysis-v3/runs/{runId}/entities`
6. `GET /workspace/analysis-v3/runs/{runId}/facts`
7. `GET /workspace/analysis-v3/runs/{runId}/cards`
8. `GET /workspace/analysis-v3/runs/{runId}/events`
9. `GET /workspace/analysis-v3/runs/{runId}/probes/plans`
10. `GET /workspace/analysis-v3/runs/{runId}/probes/results`
11. `GET /workspace/analysis-v3/runs/{runId}/backtrack/tasks`
12. `GET /workspace/analysis-v3/runs/{runId}/review`
13. `GET /workspace/books/{id}/analysis/runs`（V1）
14. `GET /workspace/analysis/runs/{v1RunId}/cards`

外加：`wsStore.connect('/ws/analysis-v3')` 建连（onopen 后由 store 发 auth 帧）。`watch(bookId)` 无 immediate，挂载时不会重复触发上述调用。

## 12. 测试未覆盖项 + 原因

- 环境修复备注：本机 node_modules 中 element-plus 实装为 2.14.1（package.json 声明 ^2.9.3），其 ESM 入口直接 `import 'element-plus/theme-chalk/base.css'`，被 vitest 外置（externalized）时 Node 报 `Unknown file extension ".css"`，导致**所有**引用 element-plus 的测试套件（含本组件、LoginDialog、DrawerPanel 等 7 个）此前整体无法加载。为此在 `vite.config.js` 的 `test.server.deps.inline` 中加入了 `element-plus` / `@element-plus/icons-vue`（仅测试基础设施，未动组件源码）。副作用：原本因加载失败被掩盖的 ContentEditor（1）、DrawerPanel（4）、WorkspaceLayout（9）共 14 条历史断言失败随之显形；原已知 20 条基线失败（api/auth/chapter/websocket/world）未受影响、无回归。

- `runV3AnalysisOverWs` 全流程（1718-1746 createV3Run 的 WS 通道）：内部有 30 分钟 setTimeout 与 10 秒 setInterval stall 检查器（1639-1646），jsdom + 真 fake timer 交织成本高；只覆盖到"挂载建连 + auth 帧"层面（wsStore 通道）。
- `runProbes` / `runMemoryLayer` / `createIncrementalV3Run` / `mergeEntities` / `splitEntity` / `rollbackEntity` / `executeBacktrackTask` / `cancelBacktrackTask` / `createEntityBacktrackTask` / `applyV1Run` / `writebackCard`：均依赖 ElMessageBox.confirm 确认链 + 多次 api 回读，mock 模式与 markEntityReviewed 相同，属低风险重复，未逐一展开（行为锁定以 markEntityReviewed 代表审核类、loadV3Runs/loadV1Runs 代表刷新类、saveWorkspaceSettings 代表设置类）。
- `copyDiagnostics` 的 clipboard 分支：jsdom 无 navigator.clipboard.writeText，会走 execCommand 兜底，收益低。
- 样式段（2574-2931）不参与行为锁定。
