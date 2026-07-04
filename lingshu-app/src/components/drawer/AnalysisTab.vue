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

        <template v-if="analysisMode === 'v1'">
          <div
            v-if="analysisV1Runs.length"
            class="result-section"
          >
            <div class="result-label">
              V1 运行记录
            </div>
            <div
              v-for="run in analysisV1Runs"
              :key="run.id"
              class="run-item"
              :class="{ active: run.id === selectedV1RunId, 'run-failed': run.status === 'failed' }"
              @click="loadV1RunCards(run.id)"
            >
              <div class="run-item-main">
                <div class="run-title">
                  #{{ run.id }} · <span :class="{ 'run-status-failed': run.status === 'failed' }">{{ runStatusText(run.status) }}</span>
                </div>
                <div class="run-meta">
                  {{ run.card_count || 0 }} 卡 · {{ run.pipeline_version || 'v1' }} · {{ run.updated_at || run.created_at }}
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
                {{ run.status === 'failed' ? '失败' : 'V1' }}
              </el-tag>
            </div>
          </div>

          <div
            v-if="selectedV1Run && selectedV1Run.status === 'failed'"
            class="run-failure-panel"
          >
            <div class="run-failure-head">
              <span class="run-failure-title">分析失败</span>
              <el-tag
                size="small"
                type="danger"
                effect="plain"
              >
                运行 #{{ selectedV1Run.id }}
              </el-tag>
            </div>
            <div class="run-failure-body">
              {{ selectedV1Run.error_text || '失败原因未知，请稍后重试或查看服务器日志。' }}
            </div>
            <div class="run-failure-time">
              {{ selectedV1Run.updated_at || selectedV1Run.created_at }}
            </div>
          </div>

          <div
            v-if="selectedV1RunId && analysisV1Cards.length"
            class="result-section"
          >
            <div class="result-label">
              V1 草案卡 ({{ analysisV1Cards.length }} 张)
            </div>
            <div
              v-for="card in analysisV1Cards"
              :key="card.id"
              class="v3-card-item"
              @click="openV1CardDetail(card)"
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
                    size="small"
                    effect="plain"
                  >
                    {{ card.card_type === 'full_payload' ? '完整分析' : card.card_type === 'characters' ? '人物' : card.card_type === 'world' ? '世界观' : card.card_type }}
                  </el-tag>
                </span>
              </div>
              <div class="v3-card-meta">
                评分 {{ confidenceText(card.ars_score) }}
              </div>
              <div
                v-if="card.payload?.summary"
                class="v3-card-summary"
              >
                {{ card.payload.summary }}
              </div>
            </div>
          </div>

          <div
            v-else-if="!loadingV1Runs && !loadingV1Cards && !analysisV1Runs.length"
            class="empty-hint"
          >
            暂无 V1 分析数据
          </div>
        </template>
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

    <!-- V1 卡片详情弹窗 -->
    <el-dialog
      v-model="v1CardDetailVisible"
      :title="v1CardDetailCard?.payload?.title || 'V1 卡片详情'"
      width="560px"
      destroy-on-close
      class="card-detail-dialog"
    >
      <template v-if="v1CardDetailCard">
        <div class="detail-section">
          <div class="detail-head">
            <span class="detail-label">基本信息</span>
            <span class="v3-card-tags">
              <el-tag
                size="small"
                :type="cardStatusTagType(v1CardDetailCard.status)"
                effect="plain"
              >
                {{ v1CardDetailCard.status === 'draft' ? '草案' : v1CardDetailCard.status === 'applied' ? '已写回' : v1CardDetailCard.status === 'superseded' ? '已取代' : v1CardDetailCard.status }}
              </el-tag>
              <el-tag
                size="small"
                effect="plain"
              >
                {{ v1CardDetailCard.card_type === 'full_payload' ? '完整分析' : v1CardDetailCard.card_type === 'characters' ? '人物' : v1CardDetailCard.card_type === 'world' ? '世界观' : v1CardDetailCard.card_type }}
              </el-tag>
            </span>
          </div>
          <div class="detail-grid">
            <div class="detail-field">
              <span class="detail-key">卡片 UID</span>
              <span class="detail-value mono">{{ v1CardDetailCard.card_uid }}</span>
            </div>
            <div class="detail-field">
              <span class="detail-key">评分</span>
              <span class="detail-value">{{ confidenceText(v1CardDetailCard.ars_score) }}</span>
            </div>
          </div>
        </div>

        <div
          v-if="v1CardDetailCard.payload"
          class="detail-section"
        >
          <div class="detail-head">
            <span class="detail-label">分析内容</span>
          </div>
          <div class="detail-summary">
            <pre class="v1-payload-preview">{{ JSON.stringify(v1CardDetailCard.payload, null, 2) }}</pre>
          </div>
        </div>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button
            size="small"
            @click="v1CardDetailVisible = false"
          >
            关闭
          </el-button>
          <el-button
            v-if="v1CardDetailCard?.status === 'applied'"
            size="small"
            type="success"
            disabled
          >
            已写回
          </el-button>
          <el-button
            v-else-if="v1CardDetailCard?.status === 'superseded'"
            size="small"
            type="warning"
            disabled
          >
            已取代
          </el-button>
          <el-button
            v-else
            size="small"
            type="primary"
            :loading="applyingV1Run"
            @click="applyV1Run(false)"
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
import api, { buildWsUrl, sendWsAuth } from '../../utils/api';

const bookStore = useBookStore();
const auth = useAuthStore();
const { on, off, emit } = useEventBus();
const wsStore = useWsStore();
const bookId = computed(() => bookStore.currentBookId);

// WebSocket 连接用于接收写回完成广播（单卡/批量）
const WS_PATH_ANALYSIS_V3 = '/ws/analysis-v3';
let _wsMessageHandler = null;

const workspaceSettings = ref({ analysis_pipeline_mode: 'v3' });
const loadingWorkspaceSettings = ref(false);
const savingWorkspaceSettings = ref(false);
const creatingV3Run = ref(false);
const analysisV3Progress = ref({ percent: 0, message: '' });
const runningIncrementalV3Run = ref(false);
const useAiAnalysis = ref(false);
const runningMemoryLayer = ref(false);
const runningProbes = ref(false);
const loadingV3Runs = ref(false);
const loadingV3Blocks = ref(false);
const loadingV3Mentions = ref(false);
const loadingV3Entities = ref(false);
const loadingV3Facts = ref(false);
const loadingV3Cards = ref(false);
const loadingV3Events = ref(false);
const loadingV3ProbePlans = ref(false);
const loadingV3ProbeResults = ref(false);
const loadingV3BacktrackTasks = ref(false);
const loadingV3Review = ref(false);
const loadingEntityVersions = ref(false);
const analysisV3Runs = ref([]);
const analysisV3Blocks = ref([]);
const analysisV3Mentions = ref([]);
const analysisV3Entities = ref([]);
const analysisV3Facts = ref([]);
const analysisV3Cards = ref([]);
const analysisV3Events = ref([]);
const analysisV3ProbePlans = ref([]);
const analysisV3ProbeResults = ref([]);
const activeProbeQuery = ref('');
const activeProbeLoading = ref(false);
const activeProbeResults = ref([]);
const analysisV3BacktrackTasks = ref([]);
const analysisV3Review = ref(null);
const entityVersionsForReview = ref([]);
const selectedV3RunId = ref(null);
const analysisV3WorkflowTab = ref('overview');
const creatingBacktrackEntityUid = ref(null);
const executingBacktrackTaskId = ref(null);
const cancellingBacktrackTaskId = ref(null);
const reviewingEntityUid = ref(null);
const runningEntityReviewAction = ref('');
const entityMergeForm = ref({
  targetUid: '',
  sourceUids: [],
  canonicalName: '',
  aliasesText: '',
});
const entitySplitForm = ref({
  sourceUid: '',
  canonicalName: '',
  mentionUids: [],
  factUids: [],
});
const entityRollbackForm = ref({
  entityUid: '',
  version: null,
});
const cardDetailVisible = ref(false);
const cardDetailCard = ref(null);
const writingBackCardUid = ref(null);
const analysisMode = ref('v3');
const analysisModeOptions = [
  { label: 'V3', value: 'v3' },
  { label: 'V1', value: 'v1' },
];
const creatingV1OneShotRun = ref(false);
const loadingV1Runs = ref(false);
const loadingV1Cards = ref(false);
const analysisV1Runs = ref([]);
const analysisV1Cards = ref([]);
const selectedV1RunId = ref(null);
const v1CardDetailVisible = ref(false);
const v1CardDetailCard = ref(null);
const applyingV1Run = ref(false);

const selectedV3Run = computed(() => analysisV3Runs.value.find(run => run.id === selectedV3RunId.value) || null);
const selectedV1Run = computed(() => analysisV1Runs.value.find(run => run.id === selectedV1RunId.value) || null);

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

const DEFAULT_V3_STAGES = [
  { key: 'init', phase: 'M0', label: '初始化' },
  { key: 'l1_semantic_blocks', phase: 'M1', label: '语义分块' },
  { key: 'entity_mentions', phase: 'M2', label: '实体提及抽取' },
  { key: 'entity_coreference', phase: 'M3', label: '共指消解' },
  { key: 'identity_resolve', phase: 'M3+', label: '身份消解' },
  { key: 'atomic_facts', phase: 'M4', label: '原子事实抽取' },
  { key: 'memory_layer', phase: 'M7', label: '记忆分层' },
  { key: 'card_events', phase: 'M5', label: '卡片生成' },
  { key: 'card_post_process', phase: 'M5+', label: '卡片后处理' },
  { key: 'probe_plans', phase: 'M8', label: '文章探针' },
  { key: 'completed', phase: 'Done', label: '完成' },
];

function normalizeV3Stages(rawStages) {
  const source = Array.isArray(rawStages) && rawStages.length ? rawStages : DEFAULT_V3_STAGES;
  return source.map((stage, index) => ({
    key: String(stage?.key || `stage_${index}`),
    phase: String(stage?.phase || `S${index + 1}`),
    label: String(stage?.label || stage?.key || `阶段 ${index + 1}`),
  }));
}

function currentV3StageIndexForRun(run) {
  const stages = normalizeV3Stages(run?.meta?.stages);
  const explicit = Number(run?.meta?.current_stage_index);
  if (Number.isFinite(explicit) && explicit >= 0) {
    return Math.min(explicit, Math.max(0, stages.length - 1));
  }
  const step = String(run?.meta?.current_step || '');
  const normalizedStep = step === 'article_probes' ? 'probe_plans' : step === 'workflow_ui' ? 'completed' : step;
  const byStep = stages.findIndex(stage => stage.key === normalizedStep);
  if (byStep >= 0) return byStep;
  const phase = String(run?.meta?.current_phase || '');
  const byPhase = stages.findIndex(stage => stage.phase === phase);
  if (byPhase >= 0) return byPhase;
  if (['probes_ready', 'completed'].includes(String(run?.status || ''))) {
    return Math.max(0, stages.length - 1);
  }
  return 0;
}

function currentV3StageTextForRun(run) {
  const stages = normalizeV3Stages(run?.meta?.stages);
  const index = currentV3StageIndexForRun(run);
  return run?.meta?.current_stage_label || stages[index]?.label || run?.meta?.current_phase || 'M0';
}

const currentV3StageIndex = computed(() => currentV3StageIndexForRun(selectedV3Run.value));

const currentV3StageText = computed(() => currentV3StageTextForRun(selectedV3Run.value));

const v3StageItems = computed(() => {
  const stages = normalizeV3Stages(selectedV3Run.value?.meta?.stages);
  const currentIndex = currentV3StageIndex.value;
  return stages.map((stage, index) => ({
    ...stage,
    state: index < currentIndex ? 'done' : index === currentIndex ? 'active' : 'pending',
  }));
});

const entityOptions = computed(() => analysisV3Entities.value.map(entity => ({
  label: entityLabel(entity),
  value: entity.entity_uid,
  status: entity.status || 'candidate',
})));

const activeEntityOptions = computed(() => entityOptions.value.filter(item => item.status !== 'merged'));

const mergeSourceOptions = computed(() => activeEntityOptions.value.filter(item => item.value !== entityMergeForm.value.targetUid));

const splitMentionOptions = computed(() => mentionsForEntity(entitySplitForm.value.sourceUid).map(mention => ({
  label: `${mention.quote_text || mention.normalized_text || shortHash(mention.mention_uid)} · ${mention.char_start}-${mention.char_end}`,
  value: mention.mention_uid,
})));

const splitFactOptions = computed(() => analysisV3Facts.value
  .filter(fact => fact.subject_entity_uid === entitySplitForm.value.sourceUid)
  .map(fact => ({
    label: `${fact.fact_type || 'fact'} · ${String(fact.quote_text || fact.fact_uid || '').slice(0, 24)}`,
    value: fact.fact_uid,
  })));

const rollbackVersionOptions = computed(() => entityVersionsForReview.value.map(version => ({
  label: `v${version.version} · ${version.action} · ${version.created_at || ''}`,
  value: version.version,
})));

const canMergeEntities = computed(() => Boolean(
  selectedV3RunId.value && entityMergeForm.value.targetUid && entityMergeForm.value.sourceUids?.length
));

const canSplitEntity = computed(() => Boolean(
  selectedV3RunId.value
  && entitySplitForm.value.sourceUid
  && String(entitySplitForm.value.canonicalName || '').trim()
  && ((entitySplitForm.value.mentionUids || []).length || (entitySplitForm.value.factUids || []).length)
));

const canRollbackEntity = computed(() => Boolean(
  selectedV3RunId.value && entityRollbackForm.value.entityUid && entityRollbackForm.value.version
));

const canWritebackCard = computed(() => {
  if (!cardDetailCard.value || !selectedV3RunId.value) return false;
  const status = cardDetailCard.value.status;
  if (status === 'applied' || status === 'superseded') return false;
  return Boolean(cardDetailCard.value.payload?.writeback_target && cardDetailCard.value.payload?.writeback_fields);
});

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

const probeConflictResults = computed(() => analysisV3ProbeResults.value.filter(result => (
  result.consistency === 'inconsistent' || result.status === 'manual_review' || result.result?.manual_review_required
)));

const probeManualReviewCount = computed(() => probeConflictResults.value.length);

const activeProbeResultsOnly = computed(() =>
  analysisV3ProbeResults.value.filter(r => r.probe_mode !== 'passive')
);
const activeProbePlansOnly = computed(() =>
  analysisV3ProbePlans.value.filter(p => p.probe_mode !== 'passive')
);

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

function runV3AnalysisOverWs() {
  return new Promise((resolve, reject) => {
    const taskId = `analysis-v3-${Date.now()}`;
    const ws = new WebSocket(buildWsUrl(WS_PATH_ANALYSIS_V3));
    let settled = false;
    let analyzeSent = false;
    let lastProgressTime = Date.now();
    const timer = setTimeout(() => {
      finish(new Error('分析超时，请稍后重试'));
    }, 30 * 60 * 1000);
    const stallChecker = setInterval(() => {
      if (Date.now() - lastProgressTime > 60000 && !settled) {
        finish(new Error('分析长时间无进度更新，可能是 AI 调用超时或服务异常，请检查 AI 配置或稍后重试'));
      }
    }, 10000);

    function cleanup() {
      clearTimeout(timer);
      clearInterval(stallChecker);
      try { ws.close(); } catch { /* ignore */ }
    }

    function finish(error, data = null) {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve(data);
    }

    ws.onopen = () => {
      const token = sendWsAuth(ws);
      if (!token) {
        finish(new Error('请先登录后再分析'));
      }
    };

    ws.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch { return; }

      if (message.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      }

      if (message.type === 'auth_ok' && !analyzeSent) {
        analyzeSent = true;
        lastProgressTime = Date.now();
        ws.send(JSON.stringify({
          type: 'analyze_v3',
          task_id: taskId,
          payload: { book_id: bookId.value, use_ai: useAiAnalysis.value },
        }));
        return;
      }

      if (message.task_id && message.task_id !== taskId) return;
      const payload = message.payload || {};

      if (message.type === 'analysis_v3.progress') {
        lastProgressTime = Date.now();
        analysisV3Progress.value = {
          percent: Number(payload.percent || 0),
          message: payload.message || '',
        };
      } else if (message.type === 'analysis_v3.result') {
        if (payload.status === 'cancelled') {
          finish(new Error('分析已取消'));
        } else {
          finish(null, payload);
        }
      } else if (message.type === 'analysis_v3.error') {
        finish(new Error(payload.message || '分析失败'));
      }
    };

    ws.onerror = () => finish(new Error('分析连接失败'));
    ws.onclose = (event) => {
      if (!settled) {
        finish(new Error(`分析连接已断开：${event.code || ''}`));
      }
    };
  });
}

async function createV3Run() {
  if (!auth.requireAiAccess()) return;
  if (!bookId.value) return;
  creatingV3Run.value = true;
  analysisV3Progress.value = { percent: 0, message: 'V3 分析启动中...' };
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
  resetEntityReviewForms();
  try {
    const data = await runV3AnalysisOverWs();
    const runId = data.run_id || data.item?.id;
    ElMessage.success('全书分析已完成');
    await loadV3Runs(runId);
  } catch (error) {
    ElMessage.error(errorMessage(error) || '分析失败');
    analysisV3Progress.value = { percent: 0, message: '' };
  } finally {
    creatingV3Run.value = false;
  }
}

async function createIncrementalV3Run() {
  if (!auth.requireAiAccess()) return;
  if (!bookId.value || !selectedV3RunId.value) return;
  runningIncrementalV3Run.value = true;
  try {
    const { data } = await api.post(`/workspace/books/${bookId.value}/analysis-v3/incremental`, {
      base_run_id: selectedV3RunId.value,
      use_ai: useAiAnalysis.value,
    });
    const runId = data.run_id || data.item?.id;
    ElMessage.success('增量更新已完成');
    await loadV3Runs(runId);
  } catch (error) {
    ElMessage.error(errorMessage(error) || '增量分析失败');
  } finally {
    runningIncrementalV3Run.value = false;
  }
}

async function createV1OneShotRun() {
  if (!auth.requireAiAccess()) return;
  if (!bookId.value) return;
  creatingV1OneShotRun.value = true;
  analysisV1Cards.value = [];
  selectedV1RunId.value = null;
  try {
    const { data } = await api.post(`/workspace/books/${bookId.value}/analysis-v1/one-shot`, { use_ai: true });
    const runId = data.run_id || data.item?.id;
    ElMessage.success('V1 一次性读完分析已完成');
    await loadV1Runs(runId);
  } catch (error) {
    ElMessage.error(errorMessage(error) || 'V1 一次性读完分析失败');
  } finally {
    creatingV1OneShotRun.value = false;
  }
}

async function loadV1Runs(preferredRunId = null) {
  if (!bookId.value) return;
  loadingV1Runs.value = true;
  try {
    const { data } = await api.get(`/workspace/books/${bookId.value}/analysis/runs`);
    analysisV1Runs.value = data.items || [];
    const nextRunId = preferredRunId || selectedV1RunId.value || analysisV1Runs.value[0]?.id || null;
    if (nextRunId) await loadV1RunCards(nextRunId);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载 V1 运行记录失败');
  } finally {
    loadingV1Runs.value = false;
  }
}

async function loadV1RunCards(runId) {
  if (!runId) return;
  selectedV1RunId.value = runId;
  loadingV1Cards.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis/runs/${runId}/cards`);
    analysisV1Cards.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载 V1 草案卡失败');
  } finally {
    loadingV1Cards.value = false;
  }
}

function openV1CardDetail(card) {
  v1CardDetailCard.value = card;
  v1CardDetailVisible.value = true;
}

async function applyV1Run(allowWeakEvidence = false) {
  if (!selectedV1RunId.value) return;
  const weakEvidenceAllowed = allowWeakEvidence === true;
  const confirmed = await confirmV3Action(
    `确认将 V1 分析运行 #${selectedV1RunId.value} 的草案写回到正式数据？此操作将更新正式数据。`,
    '确认写回',
  );
  if (!confirmed) return;
  applyingV1Run.value = true;
  try {
    const { data } = await api.post(`/workspace/analysis/runs/${selectedV1RunId.value}/apply`, {
      user_override: weakEvidenceAllowed,
      allow_weak_evidence: weakEvidenceAllowed,
    });
    ElMessage.success(`写回成功：${data.applied_cards || 0} 张卡已应用`);
    v1CardDetailVisible.value = false;
    await loadV1Runs(selectedV1RunId.value);
    // 通知其他组件刷新业务数据
    emit('lingshu:characters-updated', { bookId: bookId.value, source: 'v1_writeback' });
    emit('lingshu:world-updated', { bookId: bookId.value, source: 'v1_writeback' });
    emit('lingshu:book-updated', { bookId: bookId.value, source: 'v1_writeback' });
  } catch (error) {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail;
    // 409 = 证据不足，提示用户是否弱证据覆盖
    if (status === 409 && detail?.requires_user_override) {
      const retry = await confirmV3Action(
        '分析草案证据不足，是否以弱证据模式强制写回？',
        '弱证据写回',
      );
      if (retry) {
        applyingV1Run.value = false;
        return applyV1Run(true);
      }
    }
    ElMessage.error(errorMessage(error) || '写回失败');
  } finally {
    applyingV1Run.value = false;
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

async function loadV3Blocks(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Blocks.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/blocks`);
    analysisV3Blocks.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载语义块失败');
  } finally {
    loadingV3Blocks.value = false;
  }
}

async function loadV3Mentions(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Mentions.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/mentions`);
    analysisV3Mentions.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载提及候选失败');
  } finally {
    loadingV3Mentions.value = false;
  }
}

async function loadV3Entities(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Entities.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/entities`);
    analysisV3Entities.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载实体候选失败');
  } finally {
    loadingV3Entities.value = false;
  }
}

async function loadV3Facts(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Facts.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/facts`);
    analysisV3Facts.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载原子事实失败');
  } finally {
    loadingV3Facts.value = false;
  }
}

async function loadV3Cards(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Cards.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/cards`);
    analysisV3Cards.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载 V3 草案卡失败');
  } finally {
    loadingV3Cards.value = false;
  }
}

async function loadV3Events(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Events.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/events`);
    analysisV3Events.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载 V3 卡片事件失败');
  } finally {
    loadingV3Events.value = false;
  }
}

async function runMemoryLayer() {
  if (!selectedV3RunId.value) return;
  runningMemoryLayer.value = true;
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/steps/memory_layer`);
    ElMessage.success(`记忆分层完成：${data.classified_fact_count || 0} 条事实，${data.summary_fact_count || 0} 条摘要`);
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '记忆分层失败');
  } finally {
    runningMemoryLayer.value = false;
  }
}

async function runProbes() {
  if (!selectedV3RunId.value) return;
  runningProbes.value = true;
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/steps/probes`);
    ElMessage.success(`文章探针完成：${data.probe_plan_count || 0} 个计划，${data.probe_result_count || 0} 个结果`);
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '文章探针失败');
  } finally {
    runningProbes.value = false;
  }
}

async function loadV3ProbePlans(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3ProbePlans.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/probes/plans`);
    analysisV3ProbePlans.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载文章探针计划失败');
  } finally {
    loadingV3ProbePlans.value = false;
  }
}

async function loadV3ProbeResults(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3ProbeResults.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/probes/results`);
    analysisV3ProbeResults.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载文章探针结果失败');
  } finally {
    loadingV3ProbeResults.value = false;
  }
}

async function runActiveProbe() {
  const query = activeProbeQuery.value.trim();
  if (!query) return;
  const bid = bookId.value;
  if (!bid) {
    ElMessage.warning('请先选择一本书');
    return;
  }
  activeProbeLoading.value = true;
  try {
    const { data } = await api.post(`/workspace/books/${bid}/active-probe`, { query });
    const result = { ...data, id: Date.now() };
    activeProbeResults.value.unshift(result);
    saveActiveProbeHistory(bid, result);
    activeProbeQuery.value = '';
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '主动探针执行失败');
  } finally {
    activeProbeLoading.value = false;
  }
}

function saveActiveProbeHistory(bookId, result) {
  const key = `lingshu_active_probes_${bookId}`;
  try {
    const existing = JSON.parse(localStorage.getItem(key) || '[]');
    existing.unshift(result);
    localStorage.setItem(key, JSON.stringify(existing.slice(0, 20)));
  } catch { /* ignore */ }
}

function loadActiveProbeHistory(bookId) {
  const key = `lingshu_active_probes_${bookId}`;
  try {
    activeProbeResults.value = JSON.parse(localStorage.getItem(key) || '[]');
  } catch {
    activeProbeResults.value = [];
  }
}

async function loadV3BacktrackTasks(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3BacktrackTasks.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/backtrack/tasks`);
    analysisV3BacktrackTasks.value = data.items || [];
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载回溯任务失败');
  } finally {
    loadingV3BacktrackTasks.value = false;
  }
}

async function loadV3Review(runId) {
  if (!runId) return;
  selectedV3RunId.value = runId;
  loadingV3Review.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${runId}/review`);
    analysisV3Review.value = data.item || null;
  } catch (error) {
    analysisV3Review.value = null;
    ElMessage.error(error?.response?.data?.detail || '加载审核摘要失败');
  } finally {
    loadingV3Review.value = false;
  }
}

async function createEntityBacktrackTask(entity) {
  if (!selectedV3RunId.value || !entity?.entity_uid) return;
  const confirmed = await confirmV3Action(`创建 ${entity.canonical_name || entity.entity_uid} 的回溯任务？`, '创建回溯任务');
  if (!confirmed) return;
  creatingBacktrackEntityUid.value = entity.entity_uid;
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks`, {
      trigger_type: 'entity_updated',
      target_uid: entity.entity_uid,
      reason: 'manual frontend backtrack',
    });
    ElMessage.success(`已创建回溯任务：${data.item?.impact?.counts?.cards || 0} 张卡受影响`);
    await loadV3RunDiagnostics(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '创建回溯任务失败');
  } finally {
    creatingBacktrackEntityUid.value = null;
  }
}

async function markEntityReviewed(entity) {
  if (!selectedV3RunId.value || !entity?.entity_uid) return;
  const confirmed = await confirmV3Action(`将 ${entity.canonical_name || entity.entity_uid} 标记为已审核？审核后将自动写回到对应业务表。`, '实体审核');
  if (!confirmed) return;
  reviewingEntityUid.value = entity.entity_uid;
  try {
    const { data } = await api.patch(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/entities/${entity.entity_uid}`, {
      status: 'reviewed',
      actor: 'user',
    });
    const wb = data.writeback_result;
    if (wb && wb.applied_id) {
      ElMessage.success(`实体已审核并写回：${wb.detail || wb.applied_table}`);
    } else {
      ElMessage.success('实体已标记为已审核');
    }
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
    // 通知其他组件刷新业务数据
    const entityType = entity.entity_type;
    if (entityType === 'character') {
      emit('lingshu:characters-updated', { bookId: bookId.value, source: 'review_writeback' });
    } else {
      emit('lingshu:world-updated', { bookId: bookId.value, source: 'review_writeback' });
    }
    emit('lingshu:writeback-completed', {
      bookId: bookId.value,
      runId: selectedV3RunId.value,
      entityUid: entity.entity_uid,
      writebackTarget: entityType === 'character' ? 'character' : 'world_entry',
    });
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '实体审核失败');
  } finally {
    reviewingEntityUid.value = null;
  }
}

async function loadEntityVersionsForReview(entityUid) {
  if (!selectedV3RunId.value || !entityUid) return;
  loadingEntityVersions.value = true;
  try {
    const { data } = await api.get(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/entities/${entityUid}/versions`);
    entityVersionsForReview.value = data.items || [];
  } catch (error) {
    entityVersionsForReview.value = [];
    ElMessage.error(error?.response?.data?.detail || '加载实体版本失败');
  } finally {
    loadingEntityVersions.value = false;
  }
}

async function mergeEntities() {
  if (!canMergeEntities.value || !selectedV3RunId.value) return;
  const target = findEntity(entityMergeForm.value.targetUid);
  const sourceNames = (entityMergeForm.value.sourceUids || []).map(uid => findEntity(uid)?.canonical_name || uid).join('、');
  const confirmed = await confirmV3Action(
    `将 ${sourceNames} 合并到 ${target?.canonical_name || entityMergeForm.value.targetUid}？`,
    '合并实体',
  );
  if (!confirmed) return;
  runningEntityReviewAction.value = 'merge';
  try {
    const aliases = splitCsv(entityMergeForm.value.aliasesText);
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/entities/merge`, {
      target_entity_uid: entityMergeForm.value.targetUid,
      source_entity_uids: entityMergeForm.value.sourceUids,
      canonical_name: entityMergeForm.value.canonicalName,
      aliases,
      actor: 'user',
    });
    ElMessage.success(`已合并实体，影响 ${data.backtrack_task?.impact?.counts?.cards || 0} 张卡`);
    entityMergeForm.value.sourceUids = [];
    await loadV3RunDiagnostics(selectedV3RunId.value);
    if (entityRollbackForm.value.entityUid === entityMergeForm.value.targetUid) {
      await loadEntityVersionsForReview(entityMergeForm.value.targetUid);
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '合并实体失败');
  } finally {
    runningEntityReviewAction.value = '';
  }
}

async function splitEntity() {
  if (!canSplitEntity.value || !selectedV3RunId.value) return;
  const source = findEntity(entitySplitForm.value.sourceUid);
  const confirmed = await confirmV3Action(
    `从 ${source?.canonical_name || entitySplitForm.value.sourceUid} 拆出 ${entitySplitForm.value.canonicalName}？`,
    '拆分实体',
  );
  if (!confirmed) return;
  runningEntityReviewAction.value = 'split';
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/entities/${entitySplitForm.value.sourceUid}/split`, {
      canonical_name: entitySplitForm.value.canonicalName,
      mention_uids: entitySplitForm.value.mentionUids,
      fact_uids: entitySplitForm.value.factUids,
      actor: 'user',
    });
    ElMessage.success(`已拆分实体：${data.item?.canonical_name || entitySplitForm.value.canonicalName}`);
    entitySplitForm.value.canonicalName = '';
    entitySplitForm.value.mentionUids = [];
    entitySplitForm.value.factUids = [];
    await loadV3RunDiagnostics(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '拆分实体失败');
  } finally {
    runningEntityReviewAction.value = '';
  }
}

async function rollbackEntity() {
  if (!canRollbackEntity.value || !selectedV3RunId.value) return;
  const entity = findEntity(entityRollbackForm.value.entityUid);
  const confirmed = await confirmV3Action(
    `将 ${entity?.canonical_name || entityRollbackForm.value.entityUid} 回滚到 v${entityRollbackForm.value.version}？`,
    '版本回滚',
  );
  if (!confirmed) return;
  runningEntityReviewAction.value = 'rollback';
  try {
    const { data } = await api.post(
      `/workspace/analysis-v3/runs/${selectedV3RunId.value}/entities/${entityRollbackForm.value.entityUid}/versions/${entityRollbackForm.value.version}/rollback`,
      { actor: 'user' },
    );
    ElMessage.success(`已回滚实体，影响 ${data.backtrack_task?.impact?.counts?.cards || 0} 张卡`);
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadEntityVersionsForReview(entityRollbackForm.value.entityUid);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '回滚实体失败');
  } finally {
    runningEntityReviewAction.value = '';
  }
}

async function executeBacktrackTask(task) {
  if (!selectedV3RunId.value || !task?.id) return;
  const confirmed = await confirmV3Action(`执行回溯任务 ${task.task_uid || task.id}？`, '执行回溯');
  if (!confirmed) return;
  executingBacktrackTaskId.value = task.id;
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks/${task.id}/execute`);
    ElMessage.success(`回溯完成：重算 ${data.fact_count || 0} 条事实`);
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '执行回溯失败');
  } finally {
    executingBacktrackTaskId.value = null;
  }
}

async function cancelBacktrackTask(task) {
  if (!selectedV3RunId.value || !task?.id) return;
  const confirmed = await confirmV3Action(`取消回溯任务 ${task.task_uid || task.id}？`, '取消回溯');
  if (!confirmed) return;
  cancellingBacktrackTaskId.value = task.id;
  try {
    await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/backtrack/tasks/${task.id}/cancel`);
    ElMessage.success('回溯任务已取消');
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '取消回溯任务失败');
  } finally {
    cancellingBacktrackTaskId.value = null;
  }
}

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

function findEntity(entityUid) {
  return analysisV3Entities.value.find(entity => entity.entity_uid === entityUid) || null;
}

function mentionsForEntity(entityUid) {
  return analysisV3Mentions.value.filter(mention => mention.entity_uid === entityUid);
}

function splitCsv(value) {
  return String(value || '')
    .split(/[,\n，、]/)
    .map(item => item.trim())
    .filter(Boolean);
}

function resetEntityReviewForms() {
  entityMergeForm.value = {
    targetUid: '',
    sourceUids: [],
    canonicalName: '',
    aliasesText: '',
  };
  entitySplitForm.value = {
    sourceUid: '',
    canonicalName: '',
    mentionUids: [],
    factUids: [],
  };
  entityRollbackForm.value = {
    entityUid: '',
    version: null,
  };
  entityVersionsForReview.value = [];
}

function canCancelBacktrackTask(task) {
  return task && !['running', 'completed', 'cancelled'].includes(task.status);
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

function openCardDetail(card) {
  cardDetailCard.value = card;
  cardDetailVisible.value = true;
}

function cardStatusTagType(status) {
  if (status === 'applied') return 'success';
  if (status === 'draft') return 'info';
  if (status === 'superseded') return 'warning';
  return '';
}

function writebackTargetLabel(target) {
  if (target === 'character') return '人物卡';
  if (target === 'world_entry') return '世界卡';
  if (target === 'book') return '书籍卡';
  if (target === 'none') return '不写回';
  return target || '无';
}

function writebackFieldLabel(key, _target) {
  const labels = {
    name: '名称',
    role: '角色',
    profile_text: '人物描述',
    category: '分类',
    content_text: '内容',
    outline_text: '大纲',
    world_text: '世界观',
  };
  return labels[key] || key;
}

function jumpToBlock(blockUid) {
  if (!blockUid) return;
  analysisV3WorkflowTab.value = 'blocks';
  cardDetailVisible.value = false;
}

async function writebackCard(card) {
  if (!selectedV3RunId.value || !card?.card_uid) return;
  const target = writebackTargetLabel(card.payload?.writeback_target);
  const confirmed = await confirmV3Action(
    `确认将「${card.payload?.title || card.card_uid}」写回到${target}？此操作将更新正式数据。`,
    '确认写回',
  );
  if (!confirmed) return;
  writingBackCardUid.value = card.card_uid;
  try {
    const { data } = await api.post(`/workspace/analysis-v3/runs/${selectedV3RunId.value}/cards/${card.card_uid}/writeback`);
    ElMessage.success(`写回成功：${data.applied_table || ''} #${data.applied_id || ''}`);
    cardDetailVisible.value = false;
    await loadV3RunDiagnostics(selectedV3RunId.value);
    await loadV3Runs(selectedV3RunId.value);
    // 通知其他组件（CharactersTab/WorldTab 等）刷新对应业务数据
    const writebackTarget = card.payload?.writeback_target;
    if (writebackTarget === 'character') {
      emit('lingshu:characters-updated', { bookId: bookId.value, source: 'writeback' });
    } else if (writebackTarget === 'world_entry') {
      emit('lingshu:world-updated', { bookId: bookId.value, source: 'writeback' });
    } else if (writebackTarget === 'book') {
      emit('lingshu:book-updated', { bookId: bookId.value, source: 'writeback' });
    }
    emit('lingshu:writeback-completed', {
      bookId: bookId.value,
      runId: selectedV3RunId.value,
      cardUid: card.card_uid,
      appliedTable: data.applied_table,
      appliedId: data.applied_id,
      writebackTarget,
    });
  } catch (error) {
    ElMessage.error(errorMessage(error) || '写回失败');
  } finally {
    writingBackCardUid.value = null;
  }
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

watch(() => entityRollbackForm.value.entityUid, (entityUid) => {
  entityRollbackForm.value.version = null;
  entityVersionsForReview.value = [];
  if (entityUid) {
    loadEntityVersionsForReview(entityUid);
  }
});

watch(() => entitySplitForm.value.sourceUid, () => {
  entitySplitForm.value.mentionUids = [];
  entitySplitForm.value.factUids = [];
});

watch(() => entityMergeForm.value.targetUid, (targetUid) => {
  entityMergeForm.value.sourceUids = (entityMergeForm.value.sourceUids || []).filter(uid => uid !== targetUid);
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

function _setupWsListener() {
  try {
    const ws = wsStore.connect(WS_PATH_ANALYSIS_V3);
    _wsMessageHandler = (event) => {
      if (!event || !event.data) return;
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (message.type !== 'analysis_v3.writeback_completed') return;
      const payload = message.payload || {};
      // 仅处理当前书籍的写回事件
      if (payload.bookId && bookId.value && Number(payload.bookId) !== Number(bookId.value)) return;
      // 通过 eventBus 转发，让 CharactersTab/WorldTab 等组件刷新
      if (payload.batch) {
        emit('lingshu:characters-updated', { bookId: payload.bookId, source: 'ws_writeback' });
        emit('lingshu:world-updated', { bookId: payload.bookId, source: 'ws_writeback' });
        emit('lingshu:book-updated', { bookId: payload.bookId, source: 'ws_writeback' });
      }
      emit('lingshu:writeback-completed', {
        bookId: payload.bookId,
        runId: payload.run_id,
        cardUid: payload.card_uid,
        appliedTable: payload.applied_table,
        appliedId: payload.applied_id,
        // 批量写回不带 writebackTarget，依赖 store 的"不带字段则刷新"逻辑
        writebackTarget: payload.batch ? undefined : (payload.applied_table === 'characters' ? 'character'
          : payload.applied_table === 'world_entries' ? 'world_entry'
          : payload.applied_table === 'books' ? 'book' : undefined),
        source: 'ws',
      });
      // 同步刷新当前 tab 的 V3 诊断和运行列表
      if (payload.run_id && selectedV3RunId.value) {
        loadV3RunDiagnostics(selectedV3RunId.value);
        loadV3Runs(selectedV3RunId.value);
      }
    };
    ws.addEventListener('message', _wsMessageHandler);
  } catch (e) {
    // WebSocket 连接失败不影响核心功能
    console.warn('[AnalysisTab] WebSocket 连接失败:', e);
  }
}

function _teardownWsListener() {
  if (_wsMessageHandler) {
    try {
      const ws = wsStore.connections[WS_PATH_ANALYSIS_V3];
      if (ws) ws.removeEventListener('message', _wsMessageHandler);
    } catch { /* ignore */ }
    _wsMessageHandler = null;
  }
  wsStore.disconnect(WS_PATH_ANALYSIS_V3);
}
</script>

<style scoped>
.analysis-tab { padding: 4px 0; }
.section-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.tab-title { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.empty-hint { color: var(--text-placeholder); font-size: 12px; padding: 16px 0; text-align: center; }
.mode-row { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
.mode-label { font-size: 12px; color: var(--text-secondary); font-weight: 600; }
.mode-hint { font-size: 11px; color: var(--text-placeholder); margin-bottom: 8px; line-height: 1.5; }
.analysis-actions { display: flex; align-items: center; gap: 8px; }
.mode-row :deep(.el-segmented) { width: 100%; }
.mode-row :deep(.el-segmented__item) { flex: 1; min-width: 0; }
.mode-row :deep(.el-segmented__item-label) { white-space: normal; line-height: 1.25; text-align: center; }
.result-section { margin-top: 12px; }
.result-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; }
.v3-workflow { margin-top: 12px; }
.v3-workflow-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.v3-workflow-tabs :deep(.el-tabs__nav-wrap::after) { background: var(--border-light); }
.v3-workflow-tabs :deep(.el-tabs__item) { padding: 0 10px; font-size: 12px; }
.workflow-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 6px 0 8px;
}
.workflow-actions .result-label { margin-bottom: 0; }
.v3-overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.v3-metric {
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.v3-metric-value { font-size: 16px; font-weight: 700; color: var(--text-primary); line-height: 1.2; }
.v3-metric-label { margin-top: 2px; font-size: 11px; color: var(--text-placeholder); }
.v3-stage-panel {
  margin-top: 8px;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.v3-stage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.v3-stage-title {
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}
.v3-stage-progress {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-placeholder);
}
.v3-stage-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 5px;
  margin-top: 8px;
}
.v3-stage-item {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11px;
  color: var(--text-placeholder);
}
.v3-stage-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: var(--border-light);
}
.v3-stage-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.v3-stage-item.done { color: var(--text-secondary); }
.v3-stage-item.done .v3-stage-dot { background: var(--success-color, #67c23a); }
.v3-stage-item.active {
  color: var(--text-primary);
  font-weight: 600;
}
.v3-stage-item.active .v3-stage-dot { background: var(--accent-primary); }
.v3-review-line {
  margin-top: 6px;
  padding: 0 4px;
  font-size: 11px;
  color: var(--text-placeholder);
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.review-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin-bottom: 10px;
}
.review-panel {
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.review-panel-title {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.review-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 6px;
}
.review-form :deep(.el-select),
.review-form :deep(.el-input),
.review-form :deep(.el-button) {
  width: 100%;
}
.mini-chip {
  display: inline-flex;
  max-width: 100%;
  padding: 1px 6px;
  margin: 4px 4px 0 0;
  border-radius: 999px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.5;
  word-break: break-word;
}
.run-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  background: var(--bg-secondary);
}
.run-item.active { border-color: var(--accent-primary); }
.run-title { font-size: 12px; color: var(--text-primary); line-height: 1.4; }
.run-meta { font-size: 11px; color: var(--text-placeholder); margin-top: 2px; }
.run-item-main { min-width: 0; flex: 1; }
.run-failed { border-color: var(--el-color-danger-light-5, #fab6b6); background: var(--el-color-danger-light-9, #fef0f0); }
.run-status-failed { color: var(--el-color-danger, #f56c6c); font-weight: 600; }
.run-error { font-size: 11px; color: var(--el-color-danger, #f56c6c); margin-top: 4px; line-height: 1.4; word-break: break-all; }
.run-failure-panel { border: 1px solid var(--el-color-danger-light-5, #fab6b6); background: var(--el-color-danger-light-9, #fef0f0); border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.run-failure-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.run-failure-title { font-size: 13px; font-weight: 600; color: var(--el-color-danger, #f56c6c); }
.run-failure-body { font-size: 12px; color: var(--text-primary); line-height: 1.6; word-break: break-all; }
.run-failure-time { font-size: 11px; color: var(--text-placeholder); margin-top: 6px; }
.analysis-block-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.block-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.block-title { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-all; }
.block-meta { font-size: 11px; color: var(--text-placeholder); margin-bottom: 6px; }
.block-snippet {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}
.block-hash { margin-top: 6px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.mention-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.mention-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.mention-text { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.mention-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.mention-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.entity-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.entity-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.entity-text { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.entity-head-actions { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; }
.entity-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.entity-aliases {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}
.entity-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.v3-card-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
  cursor: pointer;
  transition: border-color 0.2s;
}
.v3-card-item:hover {
  border-color: var(--el-color-primary-light-3);
}
.v3-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.v3-card-title { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.v3-card-tags { display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0; }
.v3-card-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.v3-card-summary {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}
.v3-card-wb-preview {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.wb-field-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
}
.v3-card-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.v3-card-paths { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.path-chip { font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); }
.path-more { font-size: 11px; color: var(--text-placeholder); }

/* 卡片详情弹窗 */
.detail-section { margin-bottom: 16px; }
.detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.detail-label { font-weight: 600; font-size: 13px; }
.detail-count { font-size: 11px; color: var(--text-placeholder); background: var(--el-fill-color-light); padding: 1px 6px; border-radius: 3px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.detail-field { display: flex; flex-direction: column; gap: 2px; }
.detail-key { font-size: 11px; color: var(--text-placeholder); }
.detail-value { font-size: 13px; }
.detail-value.mono { font-family: monospace; font-size: 12px; }
.detail-summary { font-size: 13px; line-height: 1.6; color: var(--text-secondary); background: var(--el-fill-color-lighter); padding: 8px 12px; border-radius: 4px; }
.diff-table { border: 1px solid var(--border-light); border-radius: 4px; overflow: hidden; }
.diff-row { display: flex; border-bottom: 1px solid var(--el-border-color-extra-light); }
.diff-row:last-child { border-bottom: none; }
.diff-key { width: 100px; flex-shrink: 0; font-size: 12px; font-weight: 500; padding: 6px 10px; background: var(--el-fill-color-lighter); color: var(--text-placeholder); }
.diff-value { flex: 1; padding: 6px 10px; font-size: 12px; }
.diff-new { color: var(--el-color-success-dark-2); }
.diff-empty { color: var(--text-placeholder); font-style: italic; }
.paths-list { display: flex; flex-wrap: wrap; gap: 4px; }
.path-tag { font-size: 11px; padding: 2px 8px; border-radius: 3px; background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); border: 1px solid var(--el-color-warning-light-7); }
.evidence-list { max-height: 200px; overflow-y: auto; }
.evidence-item { padding: 6px 8px; border-bottom: 1px solid var(--el-border-color-extra-light); cursor: pointer; transition: background 0.15s; }
.evidence-item:hover { background: var(--el-fill-color-light); }
.evidence-quote { font-size: 12px; line-height: 1.5; color: var(--text-secondary); }
.evidence-loc { font-size: 11px; color: var(--text-placeholder); font-family: monospace; margin-top: 2px; }
.evidence-more { font-size: 11px; color: var(--text-placeholder); padding: 6px 8px; text-align: center; }
.deps-list { display: flex; flex-wrap: wrap; gap: 4px; }
.dep-chip { font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--el-fill-color); font-family: monospace; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; }
.event-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.event-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.event-text { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.event-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.event-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.active-probe-search { margin-bottom: 12px; }
.active-probe-item { padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.active-probe-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.active-probe-query { font-weight: 500; font-size: 13px; }
.active-probe-summary { font-size: 12px; color: var(--el-text-color-regular); margin-bottom: 4px; line-height: 1.5; }
.active-probe-refs { margin-bottom: 4px; }
.active-probe-ref { font-size: 11px; color: var(--el-text-color-secondary); padding-left: 8px; border-left: 2px solid var(--el-color-primary-light-5); margin-bottom: 2px; }
.active-probe-meta { font-size: 11px; color: var(--el-text-color-placeholder); }
.probe-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.probe-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.probe-text { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.probe-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.probe-summary {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.5;
  word-break: break-word;
}
.probe-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.backtrack-item {
  padding: 8px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
}
.backtrack-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.backtrack-text { min-width: 0; font-size: 12px; font-weight: 600; color: var(--text-primary); word-break: break-word; }
.backtrack-meta { font-size: 11px; color: var(--text-placeholder); line-height: 1.5; }
.backtrack-rule { margin-top: 4px; font-size: 10px; color: var(--text-placeholder); word-break: break-all; }
.backtrack-actions { display: flex; justify-content: flex-end; margin-top: 4px; }
.v1-payload-preview {
  margin: 0;
  padding: 8px;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  font-family: monospace;
}
</style>
