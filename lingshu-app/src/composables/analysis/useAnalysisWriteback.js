// AnalysisTab 域拆分：V3 卡片写回（卡片详情弹窗状态 / 写回 / 标签文案 / 证据跳转）
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { ref, computed } from 'vue';
import { ElMessage } from 'element-plus';
import api from '../../utils/api';

export function useAnalysisWriteback(ctx) {
  const { selectedV3RunId, analysisV3WorkflowTab, confirmV3Action, emit, bookId } = ctx;

  const cardDetailVisible = ref(false);
  const cardDetailCard = ref(null);
  const writingBackCardUid = ref(null);

  const canWritebackCard = computed(() => {
    if (!cardDetailCard.value || !selectedV3RunId.value) return false;
    const status = cardDetailCard.value.status;
    if (status === 'applied' || status === 'superseded') return false;
    return Boolean(cardDetailCard.value.payload?.writeback_target && cardDetailCard.value.payload?.writeback_fields);
  });

  function openCardDetail(card) {
    cardDetailCard.value = card;
    cardDetailVisible.value = true;
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
      await ctx.loadV3RunDiagnostics(selectedV3RunId.value);
      await ctx.loadV3Runs(selectedV3RunId.value);
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
      ElMessage.error(ctx.errorMessage(error) || '写回失败');
    } finally {
      writingBackCardUid.value = null;
    }
  }

  return {
    cardDetailVisible,
    cardDetailCard,
    writingBackCardUid,
    canWritebackCard,
    openCardDetail,
    writebackTargetLabel,
    writebackFieldLabel,
    jumpToBlock,
    writebackCard,
  };
}
