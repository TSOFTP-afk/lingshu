// ContentEditor 域拆分：AI 概率标注（纯 props 派生的展示 computed，与润色无共享可变状态，故独立成域）
// ctx 为组件构造的共享上下文：props 为组件单一数据源。
// 纯搬移自 src/components/workspace/ContentEditor.vue，业务逻辑未改动。
import { computed } from 'vue';

export function useEditorAiProbability(ctx) {
  const { props } = ctx;

  const hasAiProbability = computed(() => props.aiProbabilityLevel !== 'none' || Number(props.aiProbability) > 0);
  const aiProbabilityText = computed(() => {
    if (!hasAiProbability.value) return '未进行AI检测';
    return `AI检测 ${normalizedAiProbability.value}%`;
  });
  const normalizedAiProbability = computed(() => Math.max(0, Math.min(100, Number(props.aiProbability) || 0)));
  const aiProbabilityClass = computed(() => {
    if (!hasAiProbability.value) return 'ai-probability--unknown';
    if (normalizedAiProbability.value > 80) return 'ai-probability--danger';
    if (normalizedAiProbability.value >= 30) return 'ai-probability--warning';
    return 'ai-probability--success';
  });

  return {
    hasAiProbability,
    aiProbabilityText,
    normalizedAiProbability,
    aiProbabilityClass,
  };
}
