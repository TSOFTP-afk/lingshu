// AnalysisTab 域拆分：实体审核（review / mark / merge / split / rollback + 表单联动 watch）
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useAnalysisEntities(ctx) {
  const {
    selectedV3RunId, analysisV3Entities, analysisV3Facts,
    entityLabel, shortHash, splitCsv, confirmV3Action, emit, bookId,
    findEntity, mentionsForEntity,
  } = ctx;

  const loadingV3Review = ref(false);
  const analysisV3Review = ref(null);
  const loadingEntityVersions = ref(false);
  const entityVersionsForReview = ref([]);
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
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
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
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
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
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
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
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await loadEntityVersionsForReview(entityRollbackForm.value.entityUid);
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '回滚实体失败');
    } finally {
      runningEntityReviewAction.value = '';
    }
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

  return {
    loadingV3Review,
    analysisV3Review,
    loadingEntityVersions,
    entityVersionsForReview,
    reviewingEntityUid,
    runningEntityReviewAction,
    entityMergeForm,
    entitySplitForm,
    entityRollbackForm,
    entityOptions,
    activeEntityOptions,
    mergeSourceOptions,
    splitMentionOptions,
    splitFactOptions,
    rollbackVersionOptions,
    canMergeEntities,
    canSplitEntity,
    canRollbackEntity,
    loadV3Review,
    markEntityReviewed,
    loadEntityVersionsForReview,
    mergeEntities,
    splitEntity,
    rollbackEntity,
    resetEntityReviewForms,
  };
}
