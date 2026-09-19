<!--
  AnalysisTab（全书分析）——结构总览（2026-09 拆解自 2931 行单文件）：
  - 共享状态与调度（bookId/selectedV3RunId/loadV3Runs/loadV3RunDiagnostics/工具函数/confirmV3Action）留在本组件，经 ctx 单一数据源传给各 composable；
  - WebSocket/鉴权/写回广播：src/composables/analysis/useAnalysisSocket.js；
  - V3 运行与明细：useAnalysisV3Runs.js；探针：useAnalysisProbes.js；回溯：useAnalysisBacktrack.js；
  - 实体审核：useAnalysisEntities.js；卡片写回：useAnalysisWriteback.js；V1 一次性管线：useAnalysisV1Legacy.js；
  - V1 模式 UI（含 V1 卡片详情弹窗）：AnalysisV1Panel.vue（LEGACY，样式见 analysis-tab-v1.css）。
-->
<template>
  <div class="analysis-tab">
    <section class="analysis-section">
      <div class="section-head">
        <span class="tab-title">全书分析</span>
      </div>

      <div
        v-if="!bookId"
        class="empty-hint"
      >
        请先选择作品
      </div>

      <template v-else>
        <div class="mode-row">
          <span class="mode-label">分析模式</span>
          <el-segmented
            v-model="analysisMode"
            size="small"
            :options="analysisModeOptions"
            :disabled="creatingV3Run || creatingV1OneShotRun"
          />
        </div>

        <div
          v-if="analysisMode === 'v3'"
          class="mode-row"
        >
          <span class="mode-label">AI 增强</span>
          <el-switch
            v-model="useAiAnalysis"
            size="small"
            active-text="开"
            inactive-text="关"
            :disabled="creatingV3Run"
          />
        </div>

        <div
          v-if="analysisMode === 'v1'"
          class="mode-hint"
        >
          一次性读完模式将使用 AI 一次性读取全书内容并生成分析草案，适用于中短篇作品（上限 30 万字，超出请使用 V3 分析）。
        </div>

        <div class="analysis-actions">
          <el-button
            v-if="analysisMode === 'v3'"
            size="small"
            type="primary"
            :loading="creatingV3Run"
            :disabled="!bookId || !auth.isLoggedIn"
            @click="createV3Run"
          >
            开始分析
          </el-button>
          <el-button
            v-if="analysisMode === 'v3'"
            size="small"
            :loading="runningIncrementalV3Run"
            :disabled="!bookId || !auth.isLoggedIn || !selectedV3RunId"
            @click="createIncrementalV3Run"
          >
            增量更新
          </el-button>
          <el-button
            v-if="analysisMode === 'v1'"
            size="small"
            type="primary"
            :loading="creatingV1OneShotRun"
            :disabled="!bookId || !auth.isLoggedIn"
            @click="createV1OneShotRun"
          >
            分析全文
          </el-button>
          <el-button
            size="small"
            text
            :loading="analysisMode === 'v3' ? loadingV3Runs : loadingV1Runs"
            @click="analysisMode === 'v3' ? loadV3Runs() : loadV1Runs()"
          >
            刷新
          </el-button>
        </div>
        <div
          v-if="analysisMode === 'v3' && creatingV3Run"
          class="mode-hint"
        >
          {{ analysisV3Progress.message || 'V3 分析启动中...' }} {{ analysisV3Progress.percent || 0 }}%
        </div>

        <template v-if="analysisMode === 'v3'">
          <div
            v-if="analysisV3Runs.length"
            class="result-section"
          >
            <div class="result-label">
              V3 运行记录
            </div>
            <div
              v-for="run in analysisV3Runs"
              :key="run.id"
              class="run-item"
              :class="{ active: run.id === selectedV3RunId, 'run-failed': run.status === 'failed' }"
              @click="loadV3RunDiagnostics(run.id)"
            >
              <div class="run-item-main">
                <div class="run-title">
                  #{{ run.id }} · <span :class="{ 'run-status-failed': run.status === 'failed' }">{{ runStatusText(run.status) }}</span>
                </div>
                <div class="run-meta">
                  {{ run.block_count || 0 }} 块 · {{ run.entity_count || 0 }} 角色 · {{ run.fact_count || 0 }} 事件 · {{ run.card_count || 0 }} 卡 · {{ run.meta?.ai_invoked ? 'AI' : '规则' }} · {{ run.updated_at || run.created_at }}
                </div>
                <div
                  v-if="run.status === 'failed' && run.error_text"
                  class="run-error"
                >
                  失败原因：{{ run.error_text }}
                </div>
              </div>
              <el-tag
                size="small"
                :type="run.status === 'failed' ? 'danger' : 'info'"
                effect="plain"
              >
                {{ run.status === 'failed' ? '失败' : currentV3StageTextForRun(run) }}
              </el-tag>
            </div>
          </div>

          <div
            v-if="selectedV3Run && selectedV3Run.status === 'failed'"
            class="run-failure-panel"
          >
            <div class="run-failure-head">
              <span class="run-failure-title">分析失败</span>
              <el-tag
                size="small"
                type="danger"
                effect="plain"
              >
                运行 #{{ selectedV3Run.id }}
              </el-tag>
            </div>
            <div class="run-failure-body">
              {{ selectedV3Run.error_text || '失败原因未知，请稍后重试或查看服务器日志。' }}
            </div>
            <div class="run-failure-time">
              {{ selectedV3Run.updated_at || selectedV3Run.created_at }}
            </div>
          </div>

          <div
            v-if="selectedV3RunId"
            class="v3-workflow"
          >
          <el-tabs
            v-model="analysisV3WorkflowTab"
            class="v3-workflow-tabs"
          >
            <el-tab-pane
              label="概览"
              name="overview"
            >
              <div class="v3-overview-grid">
                <div
                  v-for="item in v3OverviewItems"
                  :key="item.label"
                  class="v3-metric"
                >
                  <div class="v3-metric-value">
                    {{ item.value }}
                  </div>
                  <div class="v3-metric-label">
                    {{ item.label }}
                  </div>
                </div>
              </div>
              <div
                v-if="selectedV3Run"
                class="v3-stage-panel"
              >
                <div class="v3-stage-head">
                  <span class="v3-stage-title">当前阶段</span>
                  <el-tag
                    size="small"
                    type="primary"
                    effect="plain"
                  >
                    {{ currentV3StageText }}
                  </el-tag>
                </div>
                <div class="v3-stage-progress">
                  <span>共 {{ v3StageItems.length }} 阶段</span>
                  <span>{{ currentV3StageIndex + 1 }}/{{ v3StageItems.length }}</span>
                </div>
                <div class="v3-stage-list">
                  <div
                    v-for="stage in v3StageItems"
                    :key="stage.key"
                    class="v3-stage-item"
                    :class="stage.state"
                  >
                    <span class="v3-stage-dot" />
                    <span class="v3-stage-name">{{ stage.phase }} · {{ stage.label }}</span>
                  </div>
                </div>
              </div>
              <div
                v-if="analysisV3Review"
                class="v3-review-line"
              >
                写回审核 · 候选 {{ analysisV3Review.entity_status_counts?.candidate || 0 }} · 已审 {{ analysisV3Review.entity_status_counts?.reviewed || 0 }} · 已合并 {{ analysisV3Review.entity_status_counts?.merged || 0 }} · 待回溯 {{ analysisV3Review.pending_backtrack_count || 0 }} · 探针复核 {{ analysisV3Review.manual_review_probe_count || 0 }}
              </div>
              <div class="workflow-actions">
                <el-button
                  size="small"
                  text
                  @click="copyDiagnostics('V3 运行诊断', selectedV3RunDiagnostics)"
                >
                  复制诊断
                </el-button>
              </div>
              <div
                v-if="probeConflictResults.length"
                class="result-section"
              >
                <div class="result-label">
                  冲突与复核
                </div>
                <div
                  v-for="result in probeConflictResults"
                  :key="result.id"
                  class="probe-item"
                >
                  <div class="probe-head">
                    <span class="probe-text">{{ result.result?.finding || result.probe_uid }}</span>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ result.consistency }}
                    </el-tag>
                  </div>
                  <div class="probe-meta">
                    {{ result.result?.probe_type || '-' }} · 置信 {{ confidenceText(result.confidence) }} · {{ result.status }}
                  </div>
                  <div class="probe-rule">
                    {{ result.probe_uid }}
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              label="实体"
              name="entities"
            >
              <div class="workflow-actions">
                <span class="result-label">实体候选 ({{ analysisV3Entities.length }} 个)</span>
                <el-button
                  size="small"
                  text
                  @click="copyDiagnostics('V3 实体诊断', analysisV3Entities)"
                >
                  复制
                </el-button>
              </div>
              <div class="review-grid">
                <div class="review-panel">
                  <div class="review-panel-title">
                    合并
                  </div>
                  <div class="review-form">
                    <el-select
                      v-model="entityMergeForm.targetUid"
                      size="small"
                      placeholder="目标"
                      clearable
                      filterable
                    >
                      <el-option
                        v-for="item in activeEntityOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-select
                      v-model="entityMergeForm.sourceUids"
                      size="small"
                      placeholder="来源"
                      clearable
                      filterable
                      multiple
                      collapse-tags
                      collapse-tags-tooltip
                    >
                      <el-option
                        v-for="item in mergeSourceOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-input
                      v-model="entityMergeForm.canonicalName"
                      size="small"
                      placeholder="名称"
                      clearable
                    />
                    <el-input
                      v-model="entityMergeForm.aliasesText"
                      size="small"
                      placeholder="别名"
                      clearable
                    />
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :icon="Connection"
                      :loading="runningEntityReviewAction === 'merge'"
                      :disabled="!canMergeEntities"
                      @click="mergeEntities"
                    >
                      合并
                    </el-button>
                  </div>
                </div>

                <div class="review-panel">
                  <div class="review-panel-title">
                    拆分
                  </div>
                  <div class="review-form">
                    <el-select
                      v-model="entitySplitForm.sourceUid"
                      size="small"
                      placeholder="实体"
                      clearable
                      filterable
                    >
                      <el-option
                        v-for="item in activeEntityOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-input
                      v-model="entitySplitForm.canonicalName"
                      size="small"
                      placeholder="新名称"
                      clearable
                    />
                    <el-select
                      v-model="entitySplitForm.mentionUids"
                      size="small"
                      placeholder="提及"
                      clearable
                      filterable
                      multiple
                      collapse-tags
                      collapse-tags-tooltip
                    >
                      <el-option
                        v-for="item in splitMentionOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-select
                      v-model="entitySplitForm.factUids"
                      size="small"
                      placeholder="事实"
                      clearable
                      filterable
                      multiple
                      collapse-tags
                      collapse-tags-tooltip
                    >
                      <el-option
                        v-for="item in splitFactOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      :icon="Rank"
                      :loading="runningEntityReviewAction === 'split'"
                      :disabled="!canSplitEntity"
                      @click="splitEntity"
                    >
                      拆分
                    </el-button>
                  </div>
                </div>

                <div class="review-panel">
                  <div class="review-panel-title">
                    回滚
                  </div>
                  <div class="review-form">
                    <el-select
                      v-model="entityRollbackForm.entityUid"
                      size="small"
                      placeholder="实体"
                      clearable
                      filterable
                      :loading="loadingEntityVersions"
                    >
                      <el-option
                        v-for="item in entityOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-select
                      v-model="entityRollbackForm.version"
                      size="small"
                      placeholder="版本"
                      clearable
                      filterable
                      :loading="loadingEntityVersions"
                    >
                      <el-option
                        v-for="item in rollbackVersionOptions"
                        :key="item.value"
                        :label="item.label"
                        :value="item.value"
                      />
                    </el-select>
                    <el-button
                      size="small"
                      type="warning"
                      plain
                      :icon="RefreshLeft"
                      :loading="runningEntityReviewAction === 'rollback'"
                      :disabled="!canRollbackEntity"
                      @click="rollbackEntity"
                    >
                      回滚
                    </el-button>
                  </div>
                </div>
              </div>
              <div
                v-for="entity in analysisV3Entities"
                :key="entity.id"
                class="entity-item"
              >
                <div class="entity-head">
                  <span class="entity-text">{{ entity.canonical_name }}</span>
                  <span class="entity-head-actions">
                    <el-tag
                      size="small"
                      effect="plain"
                    >{{ entity.entity_type }}</el-tag>
                    <el-button
                      size="small"
                      text
                      :loading="reviewingEntityUid === entity.entity_uid"
                      :disabled="entity.status === 'reviewed'"
                      @click="markEntityReviewed(entity)"
                    >
                      审核
                    </el-button>
                    <el-button
                      size="small"
                      type="primary"
                      text
                      :loading="creatingBacktrackEntityUid === entity.entity_uid"
                      @click="createEntityBacktrackTask(entity)"
                    >
                      回溯
                    </el-button>
                  </span>
                </div>
                <div class="entity-meta">
                  {{ entity.mention_count || 0 }} 提及 · 置信 {{ confidenceText(entity.confidence) }} · {{ entity.status || 'candidate' }}
                </div>
                <div
                  v-if="entity.aliases?.length"
                  class="entity-aliases"
                >
                  {{ entity.aliases.join('、') }}
                </div>
                <div
                  v-if="mentionsForEntity(entity.entity_uid).length"
                  class="entity-mentions"
                >
                  <span
                    v-for="mention in mentionsForEntity(entity.entity_uid).slice(0, 4)"
                    :key="mention.mention_uid"
                    class="mini-chip"
                  >
                    {{ mention.quote_text }}
                  </span>
                </div>
                <div class="entity-rule">
                  {{ entity.source_rule || 'auto_coreference' }} · {{ entity.entity_uid }}
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              label="卡片"
              name="cards"
            >
              <div class="workflow-actions">
                <span class="result-label">V3 草案卡候选 ({{ analysisV3Cards.length }} 张)</span>
                <el-button
                  size="small"
                  text
                  @click="copyDiagnostics('V3 卡片诊断', analysisV3Cards)"
                >
                  复制
                </el-button>
              </div>
              <div
                v-for="card in analysisV3Cards"
                :key="card.id"
                class="v3-card-item"
                @click="openCardDetail(card)"
              >
                <div class="v3-card-head">
                  <span class="v3-card-title">{{ card.payload?.title || card.card_uid }}</span>
                  <span class="v3-card-tags">
                    <el-tag
                      size="small"
                      :type="cardStatusTagType(card.status)"
                      effect="plain"
                    >
                      {{ card.status === 'draft' ? '草案' : card.status === 'applied' ? '已写回' : card.status === 'superseded' ? '已取代' : card.status }}
                    </el-tag>
                    <el-tag
                      v-if="card.payload?.writeback_target && card.payload.writeback_target !== 'none'"
                      size="small"
                      type="primary"
                      effect="plain"
                    >
                      {{ writebackTargetLabel(card.payload.writeback_target) }}
                    </el-tag>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ card.card_type === 'v3_world' ? '世界设定' : card.card_type === 'v3_character' ? '人物' : card.card_type === 'v3_book_summary' ? '书籍摘要' : card.card_type }}
                    </el-tag>
                  </span>
                </div>
                <div class="v3-card-meta">
                  评分 {{ confidenceText(card.ars_score) }} · {{ card.payload?.fact_count || 0 }} facts · {{ card.dependencies?.length || 0 }} 依赖
                </div>
                <div class="v3-card-summary">
                  {{ card.payload?.summary || '暂无摘要' }}
                </div>
                <div
                  v-if="card.payload?.writeback_fields"
                  class="v3-card-wb-preview"
                >
                  <span
                    v-for="(_, key) in card.payload.writeback_fields"
                    :key="key"
                    class="wb-field-chip"
                  >{{ writebackFieldLabel(String(key), card.payload.writeback_target) }}</span>
                </div>
                <div class="v3-card-rule">
                  {{ card.card_uid }} · {{ shortHash(card.diff?.dependency_hash) }}
                </div>
                <div
                  v-if="card.diff?.changed_paths?.length"
                  class="v3-card-paths"
                >
                  <span
                    v-for="path in card.diff.changed_paths.slice(0, 5)"
                    :key="path"
                    class="path-chip"
                  >{{ path }}</span>
                  <span
                    v-if="card.diff.changed_paths.length > 5"
                    class="path-more"
                  >+{{ card.diff.changed_paths.length - 5 }}</span>
                </div>
              </div>
              <div
                v-if="analysisV3Events.length"
                class="result-section"
              >
                <div class="result-label">
                  卡片事件 ({{ analysisV3Events.length }} 个)
                </div>
                <div
                  v-for="event in analysisV3Events"
                  :key="event.id"
                  class="event-item"
                >
                  <div class="event-head">
                    <span class="event-text">{{ event.payload?.card_type || event.event_type }}</span>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ event.status }}
                    </el-tag>
                  </div>
                  <div class="event-meta">
                    {{ event.payload?.fact_uids?.length || 0 }} facts · priority {{ event.priority }} · attempts {{ event.attempts }}
                  </div>
                  <div class="event-rule">
                    {{ event.event_uid }} · {{ event.payload?.card_uid || shortHash(event.payload?.dependency_hash) }}
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              label="探针"
              name="probes"
            >
              <div class="active-probe-search">
                <el-input
                  v-model="activeProbeQuery"
                  size="small"
                  placeholder="输入查询，如：张三什么时候获得宝剑"
                  clearable
                  @keyup.enter="runActiveProbe"
                >
                  <template #append>
                    <el-button
                      :loading="activeProbeLoading"
                      @click="runActiveProbe"
                    >
                      搜索
                    </el-button>
                  </template>
                </el-input>
              </div>

              <div
                v-for="result in activeProbeResults"
                :key="result.id"
                class="active-probe-item"
              >
                <div class="active-probe-head">
                  <span class="active-probe-query">{{ result.query }}</span>
                  <el-tag
                    size="small"
                    effect="plain"
                  >
                    置信 {{ confidenceText(result.confidence) }}
                  </el-tag>
                </div>
                <div class="active-probe-summary">
                  {{ result.summary }}
                </div>
                <div
                  v-if="result.references?.length"
                  class="active-probe-refs"
                >
                  <div
                    v-for="ref in result.references"
                    :key="ref.chapter_id"
                    class="active-probe-ref"
                  >
                    章节 {{ ref.chapter_id || '-' }} {{ ref.title }}：{{ ref.relevance }}
                  </div>
                </div>
                <div class="active-probe-meta">
                  {{ result.created_at || '' }} · RAG {{ result.rag_results_count || 0 }} 条
                </div>
              </div>

              <div
                v-if="activeProbeResultsOnly.length"
                class="result-section"
              >
                <div class="result-label">
                  文章探针结果 ({{ activeProbeResultsOnly.length }} 个)
                </div>
                <div
                  v-for="result in activeProbeResultsOnly"
                  :key="result.id"
                  class="probe-item"
                >
                  <div class="probe-head">
                    <span class="probe-text">{{ result.result?.probe_type || result.probe_uid }}</span>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ result.consistency }}
                    </el-tag>
                  </div>
                  <div class="probe-meta">
                    置信 {{ confidenceText(result.confidence) }} · {{ result.status }} · source {{ result.result?.source_evidence?.length || 0 }} · target {{ result.result?.target_evidence?.length || 0 }}
                  </div>
                  <div class="probe-summary">
                    {{ result.result?.finding || '暂无结论' }}
                  </div>
                  <div class="probe-rule">
                    {{ result.probe_uid }} · {{ result.result?.backtrack_task?.task_uid || 'no-backtrack' }}
                  </div>
                </div>
              </div>

              <div
                v-if="activeProbePlansOnly.length"
                class="result-section"
              >
                <div class="result-label">
                  文章探针计划 ({{ activeProbePlansOnly.length }} 个)
                </div>
                <div
                  v-for="plan in activeProbePlansOnly"
                  :key="plan.id"
                  class="probe-item"
                >
                  <div class="probe-head">
                    <span class="probe-text">{{ plan.plan?.question || plan.probe_type }}</span>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ plan.probe_type }}
                    </el-tag>
                  </div>
                  <div class="probe-meta">
                    {{ plan.status }} · priority {{ plan.priority }} · source {{ plan.plan?.source_evidence?.length || 0 }} · target {{ plan.plan?.target_evidence?.length || 0 }}
                  </div>
                  <div class="probe-summary">
                    {{ plan.plan?.expected || '等待执行' }}
                  </div>
                  <div class="probe-rule">
                    {{ plan.probe_uid }} · {{ plan.subject_entity_uid || '-' }}
                  </div>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              label="回溯"
              name="backtrack"
            >
              <div class="workflow-actions">
                <span class="result-label">回溯任务 ({{ analysisV3BacktrackTasks.length }} 个)</span>
                <el-button
                  size="small"
                  text
                  @click="copyDiagnostics('V3 回溯诊断', analysisV3BacktrackTasks)"
                >
                  复制
                </el-button>
              </div>
              <div
                v-for="task in analysisV3BacktrackTasks"
                :key="task.id"
                class="backtrack-item"
              >
                <div class="backtrack-head">
                  <span class="backtrack-text">{{ task.trigger_type }} · {{ task.target_uid }}</span>
                  <el-tag
                    size="small"
                    effect="plain"
                  >
                    {{ task.status }}
                  </el-tag>
                </div>
                <div class="backtrack-meta">
                  {{ task.impact?.counts?.entities || 0 }} 实体 · {{ task.impact?.counts?.facts || 0 }} 事实 · {{ task.impact?.counts?.cards || 0 }} 卡 · priority {{ task.priority }}
                </div>
                <div class="backtrack-rule">
                  {{ task.task_uid }} · {{ task.impact?.block_uids?.length || 0 }} blocks
                </div>
                <div class="backtrack-actions">
                  <el-button
                    size="small"
                    type="primary"
                    text
                    :loading="executingBacktrackTaskId === task.id"
                    :disabled="task.status === 'running' || task.status === 'completed' || task.status === 'cancelled'"
                    @click="executeBacktrackTask(task)"
                  >
                    执行
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    text
                    :loading="cancellingBacktrackTaskId === task.id"
                    :disabled="!canCancelBacktrackTask(task)"
                    @click="cancelBacktrackTask(task)"
                  >
                    取消
                  </el-button>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              label="区块"
              name="blocks"
            >
              <div class="workflow-actions">
                <span class="result-label">语义块诊断 ({{ analysisV3Blocks.length }} 块)</span>
                <el-button
                  size="small"
                  text
                  @click="copyDiagnostics('V3 区块诊断', { blocks: analysisV3Blocks, mentions: analysisV3Mentions })"
                >
                  复制
                </el-button>
              </div>
              <div
                v-if="analysisV3Mentions.length"
                class="result-section"
              >
                <div class="result-label">
                  提及候选 ({{ analysisV3Mentions.length }} 个)
                </div>
                <div
                  v-for="mention in analysisV3Mentions"
                  :key="mention.id"
                  class="mention-item"
                >
                  <div class="mention-head">
                    <span class="mention-text">{{ mention.quote_text }}</span>
                    <el-tag
                      size="small"
                      effect="plain"
                    >
                      {{ mention.entity_type }}
                    </el-tag>
                  </div>
                  <div class="mention-meta">
                    章节 {{ mention.chapter_id || '-' }} · {{ mention.char_start }}-{{ mention.char_end }} · 置信 {{ confidenceText(mention.confidence) }}
                  </div>
                  <div class="mention-rule">
                    {{ mention.source_rule || 'rule' }} · {{ mention.block_uid }}
                  </div>
                </div>
              </div>
              <div
                v-for="block in analysisV3Blocks"
                :key="block.id"
                class="analysis-block-item"
              >
                <div class="block-head">
                  <span class="block-title">#{{ block.chunk_index }} · {{ block.block_uid }}</span>
                  <el-tag
                    size="small"
                    effect="plain"
                  >
                    {{ block.text_length }} 字
                  </el-tag>
                </div>
                <div class="block-meta">
                  章节 {{ block.chapter_id || '-' }} · {{ block.char_start }}-{{ block.char_end }}
                </div>
                <div class="block-snippet">
                  {{ block.snippet }}
                </div>
                <div class="block-hash">
                  content {{ shortHash(block.content_hash) }} · structure {{ shortHash(block.structure_hash) }}
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>

        <div
          v-else-if="!loadingV3Runs && !loadingV3Blocks && !loadingV3Mentions && !loadingV3Entities && !loadingV3Facts && !loadingV3Cards && !loadingV3Events && !loadingV3ProbePlans && !loadingV3ProbeResults && !loadingV3BacktrackTasks && !loadingV3Review"
          class="empty-hint"
        >
          暂无 V3 诊断数据
        </div>
        </template>

        <AnalysisV1Panel
          v-model:v1-card-detail-visible="v1CardDetailVisible"
          :analysis-mode="analysisMode"
          :analysis-v1-runs="analysisV1Runs"
          :analysis-v1-cards="analysisV1Cards"
          :selected-v1-run-id="selectedV1RunId"
          :selected-v1-run="selectedV1Run"
          :loading-v1-runs="loadingV1Runs"
          :loading-v1-cards="loadingV1Cards"
          :v1-card-detail-card="v1CardDetailCard"
          :applying-v1-run="applyingV1Run"
          :run-status-text="runStatusText"
          :card-status-tag-type="cardStatusTagType"
          :confidence-text="confidenceText"
          :load-v1-run-cards="loadV1RunCards"
          :open-v1-card-detail="openV1CardDetail"
          :apply-v1-run="applyV1Run"
        />
      </template>
    </section>

    <!-- 卡片详情弹窗 -->
    <el-dialog
      v-model="cardDetailVisible"
      :title="cardDetailCard?.payload?.title || '卡片详情'"
      width="560px"
      destroy-on-close
      class="card-detail-dialog"
    >
      <template v-if="cardDetailCard">
        <div class="detail-section">
          <div class="detail-head">
            <span class="detail-label">基本信息</span>
            <span class="v3-card-tags">
              <el-tag
                size="small"
                :type="cardStatusTagType(cardDetailCard.status)"
                effect="plain"
              >
                {{ cardDetailCard.status === 'draft' ? '草案' : cardDetailCard.status === 'applied' ? '已写回' : cardDetailCard.status === 'superseded' ? '已取代' : cardDetailCard.status }}
              </el-tag>
              <el-tag
                v-if="cardDetailCard.payload?.writeback_target && cardDetailCard.payload.writeback_target !== 'none'"
                size="small"
                :type="cardDetailCard.payload.writeback_target === 'character' ? 'danger' : cardDetailCard.payload.writeback_target === 'world_entry' ? '' : 'warning'"
                effect="plain"
              >
                {{ writebackTargetLabel(cardDetailCard.payload.writeback_target) }}
              </el-tag>
            </span>
          </div>
          <div class="detail-grid">
            <div class="detail-field">
              <span class="detail-key">卡片 UID</span>
              <span class="detail-value mono">{{ cardDetailCard.card_uid }}</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">类型</span>
              <span class="detail-value">{{ cardDetailCard.card_type === 'v3_world' ? '世界设定' : cardDetailCard.card_type === 'v3_character' ? '人物' : cardDetailCard.card_type === 'v3_book_summary' ? '书籍摘要' : cardDetailCard.card_type }}</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">评分</span>
              <span class="detail-value">{{ confidenceText(cardDetailCard.ars_score) }}</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">实体</span>
              <span class="detail-value mono">{{ shortHash(cardDetailCard.entity_uid) }}</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">Facts</span>
              <span class="detail-value">{{ cardDetailCard.payload?.fact_count || 0 }} 条</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">依赖</span>
              <span class="detail-value">{{ cardDetailCard.dependencies?.length || 0 }} 项</span>
            </div>
          </div>
        </div>

        <div
          v-if="cardDetailCard.payload?.summary"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">摘要</span>
          </div>
          <div class="detail-summary">
            {{ cardDetailCard.payload.summary }}
          </div>
        </div>

        <!-- 写回差异预览 -->
        <div
          v-if="cardDetailCard.payload?.writeback_fields"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">写回差异预览</span>
            <el-tag
              v-if="cardDetailCard.payload.writeback_target"
              size="small"
              :type="cardDetailCard.payload.writeback_target === 'character' ? 'danger' : cardDetailCard.payload.writeback_target === 'world_entry' ? '' : 'warning'"
              effect="plain"
            >
              {{ writebackTargetLabel(cardDetailCard.payload.writeback_target) }}
            </el-tag>
          </div>
          <div class="diff-table">
            <div
              v-for="(value, key) in cardDetailCard.payload.writeback_fields"
              :key="key"
              class="diff-row"
            >
              <div class="diff-key">
                {{ writebackFieldLabel(String(key), cardDetailCard.payload.writeback_target) }}
              </div>
              <div class="diff-value">
                <span
                  v-if="String(value || '').trim()"
                  class="diff-new"
                >{{ String(value) }}</span>
                <span
                  v-else
                  class="diff-empty"
                >（空）</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Changed Paths -->
        <div
          v-if="cardDetailCard.diff?.changed_paths?.length"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">变更路径</span>
            <span class="detail-count">{{ cardDetailCard.diff.changed_paths.length }}</span>
          </div>
          <div class="paths-list">
            <span
              v-for="path in cardDetailCard.diff.changed_paths"
              :key="path"
              class="path-tag"
            >{{ path }}</span>
          </div>
        </div>

        <!-- 证据引用 -->
        <div
          v-if="cardDetailCard.diff?.evidence_refs?.length"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">证据引用</span>
            <span class="detail-count">{{ cardDetailCard.diff.evidence_refs.length }}</span>
          </div>
          <div class="evidence-list">
            <div
              v-for="(evidenceRef, idx) in cardDetailCard.diff.evidence_refs.slice(0, 20)"
              :key="idx"
              class="evidence-item"
              @click="jumpToBlock(evidenceRef.block_uid)"
            >
              <div class="evidence-quote">
                {{ evidenceRef.quote_text || '（无引用文本）' }}
              </div>
              <div class="evidence-loc">
                block {{ shortHash(evidenceRef.block_uid) }} · fact {{ shortHash(evidenceRef.fact_uid) }}
              </div>
            </div>
            <div
              v-if="cardDetailCard.diff.evidence_refs.length > 20"
              class="evidence-more"
            >
              还有 {{ cardDetailCard.diff.evidence_refs.length - 20 }} 条引用...
            </div>
          </div>
        </div>

        <!-- 依赖 -->
        <div
          v-if="cardDetailCard.dependencies?.length"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">依赖</span>
            <span class="detail-count">{{ cardDetailCard.dependencies.length }}</span>
          </div>
          <div class="deps-list">
            <span
              v-for="dep in cardDetailCard.dependencies.slice(0, 10)"
              :key="dep.id"
              class="dep-chip"
            >
              {{ dep.dependency_type }}:{{ shortHash(dep.dependency_uid) }}
            </span>
          </div>
        </div>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button
            size="small"
            @click="cardDetailVisible = false"
          >
            关闭
          </el-button>
          <el-button
            v-if="cardDetailCard?.status === 'applied'"
            size="small"
            type="success"
            disabled
          >
            已写回
          </el-button>
          <el-button
            v-else-if="cardDetailCard?.status === 'superseded'"
            size="small"
            type="warning"
            disabled
          >
            已取代
          </el-button>
          <el-button
            v-else-if="!cardDetailCard?.payload?.writeback_target || cardDetailCard?.payload?.writeback_target === 'none'"
            size="small"
            disabled
          >
            无写回目标
          </el-button>
          <el-button
            v-else-if="!cardDetailCard?.payload?.writeback_fields"
            size="small"
            disabled
          >
            无写回字段
          </el-button>
          <el-button
            v-else
            size="small"
            type="primary"
            :loading="writingBackCardUid === cardDetailCard?.card_uid"
            @click="writebackCard(cardDetailCard)"
          >
            确认写回
          </el-button>
        </div>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Connection, Rank, RefreshLeft } from '@element-plus/icons-vue';
import { useBookStore } from '../../stores/book';
import { useAuthStore } from '../../stores/auth';
import { useEventBus } from '../../composables/useEventBus';
import { useWsStore } from '../../stores/websocket';
import api from '../../utils/api';
import { useAnalysisSocket } from '../../composables/analysis/useAnalysisSocket';
import { useAnalysisV3Runs } from '../../composables/analysis/useAnalysisV3Runs';
import { useAnalysisProbes } from '../../composables/analysis/useAnalysisProbes';
import { useAnalysisBacktrack } from '../../composables/analysis/useAnalysisBacktrack';
import { useAnalysisEntities } from '../../composables/analysis/useAnalysisEntities';
import { useAnalysisWriteback } from '../../composables/analysis/useAnalysisWriteback';
import { useAnalysisV1Legacy } from '../../composables/analysis/useAnalysisV1Legacy';

const bookStore = useBookStore();
const auth = useAuthStore();
const { on, off, emit } = useEventBus();
const wsStore = useWsStore();
const bookId = computed(() => bookStore.currentBookId);

const workspaceSettings = ref({ analysis_pipeline_mode: 'v3' });
const loadingWorkspaceSettings = ref(false);
const savingWorkspaceSettings = ref(false);
const selectedV3RunId = ref(null);
const analysisMode = ref('v3');
const analysisModeOptions = [
  { label: 'V3', value: 'v3' },
  { label: 'V1', value: 'v1' },
];

// 跨域共享上下文：各 composable 通过 ctx 延迟引用共享状态/函数（单一数据源，禁止复制）
const ctx = {
  auth, wsStore, on, off, emit, bookId, selectedV3RunId,
  errorMessage, shortHash, confidenceText, entityLabel, splitCsv, confirmV3Action,
};

// WebSocket 域（连接 / 鉴权 / 写回广播监听 / 一次性分析通道）
Object.assign(ctx, useAnalysisSocket(ctx));
const { _setupWsListener, _teardownWsListener } = ctx;

// V3 运行记录 / 明细域
Object.assign(ctx, useAnalysisV3Runs(ctx));
const {
  creatingV3Run, analysisV3Progress, runningIncrementalV3Run, useAiAnalysis,
  loadingV3Runs, loadingV3Blocks, loadingV3Mentions, loadingV3Entities, loadingV3Facts, loadingV3Cards, loadingV3Events,
  analysisV3Runs, analysisV3Blocks, analysisV3Mentions, analysisV3Entities, analysisV3Facts, analysisV3Cards, analysisV3Events,
  analysisV3WorkflowTab, selectedV3Run,
  currentV3StageTextForRun, currentV3StageIndex, currentV3StageText, v3StageItems,
  loadV3Blocks, loadV3Mentions, loadV3Entities, loadV3Facts, loadV3Cards, loadV3Events,
  createV3Run, createIncrementalV3Run,
} = ctx;

// 探针域（文章探针 / 主动探针 / 冲突复核）
Object.assign(ctx, useAnalysisProbes(ctx));
const {
  loadingV3ProbePlans, loadingV3ProbeResults,
  analysisV3ProbePlans, analysisV3ProbeResults,
  activeProbeQuery, activeProbeLoading, activeProbeResults,
  probeConflictResults, probeManualReviewCount,
  activeProbeResultsOnly, activeProbePlansOnly,
  loadV3ProbePlans, loadV3ProbeResults,
  runActiveProbe, loadActiveProbeHistory,
} = ctx;

// 回溯域（回溯任务加载 / 创建 / 执行 / 取消）
Object.assign(ctx, useAnalysisBacktrack(ctx));
const {
  loadingV3BacktrackTasks, analysisV3BacktrackTasks,
  creatingBacktrackEntityUid, executingBacktrackTaskId, cancellingBacktrackTaskId,
  loadV3BacktrackTasks, createEntityBacktrackTask,
  executeBacktrackTask, cancelBacktrackTask, canCancelBacktrackTask,
} = ctx;

// 共享查找工具（依赖 V3 明细状态，供实体审核域与模板共用）
function findEntity(entityUid) {
  return ctx.analysisV3Entities.value.find(entity => entity.entity_uid === entityUid) || null;
}

function mentionsForEntity(entityUid) {
  return ctx.analysisV3Mentions.value.filter(mention => mention.entity_uid === entityUid);
}

Object.assign(ctx, { findEntity, mentionsForEntity });

// 实体审核域（review / mark / merge / split / rollback + 表单 watch）
Object.assign(ctx, useAnalysisEntities(ctx));
const {
  loadingV3Review, analysisV3Review,
  loadingEntityVersions, entityVersionsForReview,
  reviewingEntityUid, runningEntityReviewAction,
  entityMergeForm, entitySplitForm, entityRollbackForm,
  entityOptions, activeEntityOptions, mergeSourceOptions,
  splitMentionOptions, splitFactOptions, rollbackVersionOptions,
  canMergeEntities, canSplitEntity, canRollbackEntity,
  loadV3Review, markEntityReviewed,
  mergeEntities, splitEntity, rollbackEntity, resetEntityReviewForms,
} = ctx;

// 写回域（V3 卡片详情 / 写回 / 标签文案 / 证据跳转）
Object.assign(ctx, useAnalysisWriteback(ctx));
const {
  cardDetailVisible, cardDetailCard, writingBackCardUid,
  openCardDetail, writebackCard,
  writebackTargetLabel, writebackFieldLabel, jumpToBlock,
} = ctx;

// V1 一次性管线（LEGACY，仅握手兼容保留）
Object.assign(ctx, useAnalysisV1Legacy(ctx));
const {
  creatingV1OneShotRun, loadingV1Runs, loadingV1Cards,
  analysisV1Runs, analysisV1Cards, selectedV1RunId,
  v1CardDetailVisible, v1CardDetailCard, applyingV1Run,
  selectedV1Run, createV1OneShotRun,
  loadV1Runs, loadV1RunCards, openV1CardDetail, applyV1Run,
} = ctx;

const RUN_STATUS_TEXT = {
  created: '已创建',
  pending: '排队中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};
function runStatusText(status) {
  return RUN_STATUS_TEXT[status] || status || '';
}

const v3OverviewItems = computed(() => {
  const run = selectedV3Run.value || {};
  return [
    { label: '章节块', value: run.block_count || analysisV3Blocks.value.length || 0 },
    { label: '角色', value: run.entity_count || analysisV3Entities.value.length || 0 },
    { label: '事件', value: run.fact_count || analysisV3Facts.value.length || 0 },
    { label: '摘要', value: run.memory_summary_fact_count || 0 },
    { label: '设定卡', value: run.card_count || analysisV3Cards.value.length || 0 },
    { label: '一致性问题', value: run.probe_result_count || analysisV3ProbeResults.value.length || 0 },
    { label: '待审核', value: probeManualReviewCount.value },
    { label: '回溯', value: analysisV3BacktrackTasks.value.length || 0 },
  ];
});

const selectedV3RunDiagnostics = computed(() => ({
  run: selectedV3Run.value,
  counts: {
    blocks: analysisV3Blocks.value.length,
    mentions: analysisV3Mentions.value.length,
    entities: analysisV3Entities.value.length,
    facts: analysisV3Facts.value.length,
    cards: analysisV3Cards.value.length,
    events: analysisV3Events.value.length,
    probe_plans: analysisV3ProbePlans.value.length,
    probe_results: analysisV3ProbeResults.value.length,
    backtrack_tasks: analysisV3BacktrackTasks.value.length,
  },
  review: analysisV3Review.value,
  probe_conflicts: probeConflictResults.value,
}));

function onBookAnalysisStart() {
  emit('lingshu:drawer-tab', { name: 'analysis' });
  if (!bookId.value) {
    ElMessage.warning('请先选择作品');
    return;
  }
  if (analysisMode.value === 'v1') {
    createV1OneShotRun();
  } else {
    createV3Run();
  }
}

async function loadWorkspaceSettings() {
  loadingWorkspaceSettings.value = true;
  try {
    const { data } = await api.get('/settings/workspace');
    workspaceSettings.value = {
      analysis_pipeline_mode: data.analysis_pipeline_mode || 'v3',
    };
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载工作台设置失败');
  } finally {
    loadingWorkspaceSettings.value = false;
  }
}

async function saveWorkspaceSettings() {
  savingWorkspaceSettings.value = true;
  try {
    const { data } = await api.put('/settings/workspace', workspaceSettings.value);
    workspaceSettings.value = {
      analysis_pipeline_mode: data.analysis_pipeline_mode || 'v3',
    };
    ElMessage.success('工作台设置已保存');
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存工作台设置失败');
  } finally {
    savingWorkspaceSettings.value = false;
  }
}

async function loadV3Runs(preferredRunId = null) {
  if (!bookId.value) return;
  loadingV3Runs.value = true;
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/analysis-v3/runs`);
    analysisV3Runs.value = data.items || [];
    const nextRunId = preferredRunId || selectedV3RunId.value || analysisV3Runs.value[0]?.id || null;
    if (nextRunId) await loadV3RunDiagnostics(nextRunId);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载 V3 运行记录失败');
  } finally {
    loadingV3Runs.value = false;
  }
}

async function loadV3RunDiagnostics(runId) {
  if (!runId) return;
  const switchedRun = selectedV3RunId.value !== runId;
  selectedV3RunId.value = runId;
  if (switchedRun) resetEntityReviewForms();
  await Promise.all([
    loadV3Blocks(runId),
    loadV3Mentions(runId),
    loadV3Entities(runId),
    loadV3Facts(runId),
    loadV3Cards(runId),
    loadV3Events(runId),
    loadV3ProbePlans(runId),
    loadV3ProbeResults(runId),
    loadV3BacktrackTasks(runId),
    loadV3Review(runId),
  ]);
}

// 共享加载调度注册进 ctx，供各 composable / WS 回调延迟引用（单一数据源）
Object.assign(ctx, { loadV3Runs, loadV3RunDiagnostics });

function errorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return detail.message || '';
  return error?.message || '';
}

function shortHash(value) {
  return String(value || '').slice(0, 10) || '-';
}

function confidenceText(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function entityLabel(entity) {
  return `${entity.canonical_name || shortHash(entity.entity_uid)} · ${entity.status || 'candidate'}`;
}

function splitCsv(value) {
  return String(value || '')
    .split(/[,\n，、]/)
    .map(item => item.trim())
    .filter(Boolean);
}

async function copyDiagnostics(label, payload) {
  const text = JSON.stringify(payload || {}, null, 2);
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', 'readonly');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    ElMessage.success(`${label}已复制`);
  } catch {
    ElMessage.error('复制失败');
  }
}

function cardStatusTagType(status) {
  if (status === 'applied') return 'success';
  if (status === 'draft') return 'info';
  if (status === 'superseded') return 'warning';
  return '';
}

async function confirmV3Action(message, title = '确认操作') {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    });
    return true;
  } catch {
    return false;
  }
}

watch(bookId, () => {
  analysisV3Runs.value = [];
  analysisV3Blocks.value = [];
  analysisV3Mentions.value = [];
  analysisV3Entities.value = [];
  analysisV3Facts.value = [];
  analysisV3Cards.value = [];
  analysisV3Events.value = [];
  analysisV3ProbePlans.value = [];
  analysisV3ProbeResults.value = [];
  analysisV3BacktrackTasks.value = [];
  analysisV3Review.value = null;
  entityVersionsForReview.value = [];
  selectedV3RunId.value = null;
  analysisV1Runs.value = [];
  analysisV1Cards.value = [];
  selectedV1RunId.value = null;
  resetEntityReviewForms();
  loadActiveProbeHistory(bookId.value);
  loadV3Runs();
  loadV1Runs();
});

onMounted(() => {
  on('lingshu:book-analysis-start', onBookAnalysisStart);
  loadWorkspaceSettings();
  loadV3Runs();
  loadV1Runs();
  // 接入 WebSocket 接收写回完成广播
  _setupWsListener();
});

onUnmounted(() => {
  off('lingshu:book-analysis-start', onBookAnalysisStart);
  _teardownWsListener();
});
</script>

<style scoped src="./analysis-tab.css"></style>
