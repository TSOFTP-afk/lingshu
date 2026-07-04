export const DEFAULT_AI_PROVIDER = 'custom';
export const DEFAULT_BASE_URL = 'https://api.openai.com/v1';

// 思考深度档位（reasoning_effort）—— 仅当厂商 supports_reasoning_effort=true 时生效
// 不同厂商支持的档位略有差异，由 reasoning_effort_levels 指定可选值
export const REASONING_EFFORT_LABELS = {
  minimal: '极简（最快）',
  low: '低',
  medium: '中（默认）',
  high: '高',
  xhigh: '极高（最慢但最深）',
};

export const MODEL_PROVIDERS = [
  {
    label: '自定义 / OpenAI 兼容',
    value: DEFAULT_AI_PROVIDER,
    base_url: DEFAULT_BASE_URL,
    default_model: '',
  },
  {
    label: 'OpenAI',
    value: 'openai',
    base_url: DEFAULT_BASE_URL,
    default_model: 'gpt-5.6-sol',
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['minimal', 'low', 'medium', 'high', 'xhigh'],
  },
  {
    label: 'DeepSeek',
    value: 'deepseek',
    base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-v4-flash',
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['low', 'medium', 'high'],
  },
  {
    label: '阿里云百炼 / 通义千问',
    value: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen3.7-max',
    // Qwen 仅支持 enable_thinking 开关，不支持分档
    supports_reasoning_effort: false,
  },
  {
    label: '硅基流动',
    value: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
    default_model: 'deepseek-ai/DeepSeek-V4',
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['low', 'medium', 'high'],
  },
  {
    label: '火山方舟 / 豆包',
    value: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    default_model: 'doubao-seed-2.1-pro',
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['minimal', 'low', 'medium', 'high'],
  },
  {
    label: '腾讯云混元',
    value: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
    default_model: 'hunyuan-turbo-s',
    supports_reasoning_effort: false,
  },
  {
    label: 'Moonshot / Kimi',
    value: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
    default_model: 'kimi-k2.6',
    supports_reasoning_effort: false,
  },
  {
    label: '智谱 GLM',
    value: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    default_model: 'glm-5-plus',
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['low', 'medium', 'high'],
  },
  {
    label: 'OpenRouter',
    value: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
    default_model: 'openai/gpt-5.6-sol',
    // OpenRouter 聚合平台，部分上游模型支持 reasoning_effort，由具体模型决定
    supports_reasoning_effort: true,
    reasoning_effort_levels: ['minimal', 'low', 'medium', 'high', 'xhigh'],
  },
  {
    label: 'Anthropic Claude',
    value: 'anthropic',
    // Anthropic 原生 API 是 /v1/messages（非 OpenAI 协议），但官方提供 OpenAI 兼容端点
    // 完整路径：https://api.anthropic.com/v1/openai/v1/chat/completions
    base_url: 'https://api.anthropic.com/v1/openai/v1',
    default_model: 'claude-opus-4-6',
    // Anthropic 用 thinking 参数（type + budget_tokens），与 thinking_enabled 开关兼容
    // 不支持 OpenAI 风格的 reasoning_effort 分档
    supports_reasoning_effort: false,
  },
  {
    label: 'Groq',
    value: 'groq',
    base_url: 'https://api.groq.com/openai/v1',
    default_model: 'llama-3.3-70b-versatile',
    supports_reasoning_effort: false,
  },
  {
    label: 'PPIO',
    value: 'ppio',
    base_url: 'https://api.ppinfra.com/v3/openai',
    default_model: '',
    supports_reasoning_effort: false,
  },
];

export const MODEL_PRESETS = [
  // ===== OpenAI =====（GPT-5.6 系列 2026-06-27 发布，全部支持 reasoning_effort 分档）
  {
    label: 'GPT-5.6 Sol (旗舰)',
    value: 'gpt-5.6-sol',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.6 Terra (均衡)',
    value: 'gpt-5.6-terra',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.6 Luna (轻量)',
    value: 'gpt-5.6-luna',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.5 (前代旗舰)',
    value: 'gpt-5.5',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  // GPT-5.4 系列 2026-03-06 发布，主力版带 Thinking 模式；mini/nano 3月17日跟进
  {
    label: 'GPT-5.4 (主力版·Thinking)',
    value: 'gpt-5.4',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.4 Pro (高算力)',
    value: 'gpt-5.4-pro',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.4 mini (轻量)',
    value: 'gpt-5.4-mini',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5.4 nano (极速)',
    value: 'gpt-5.4-nano',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  // GPT-5.3-codex 2026-03 初发布，仅 codex 编程版，无 5.3 主体版本
  {
    label: 'GPT-5.3 Codex (编程专用)',
    value: 'gpt-5.3-codex',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5',
    value: 'gpt-5',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5 mini',
    value: 'gpt-5-mini',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'GPT-5 nano',
    value: 'gpt-5-nano',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },

  // ===== DeepSeek =====（V4-Pro 与 V4-Flash 均支持思考模式，由 thinking_enabled 开关控制，
  //                       不再硬编码 thinking_enabled，避免误导成"推理版/快速版"）
  {
    label: 'DeepSeek V4 Pro (性能旗舰)',
    value: 'deepseek-v4-pro',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
  },
  {
    label: 'DeepSeek V4 Flash (轻量快速)',
    value: 'deepseek-v4-flash',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
  },

  // ===== 阿里云百炼 / 通义千问 =====（Qwen 仅支持 enable_thinking 开关，不支持分档）
  {
    label: 'Qwen3.7 Max (旗舰推理)',
    value: 'qwen3.7-max',
    provider: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    label: 'Qwen3.7 Plus (多模态均衡)',
    value: 'qwen3.7-plus',
    provider: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    label: 'Qwen3.7 Flash (轻量高效)',
    value: 'qwen3.7-flash',
    provider: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    label: 'Qwen3 Coder Plus (编程专用)',
    value: 'qwen3-coder-plus',
    provider: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },

  // ===== 硅基流动 =====
  {
    label: 'DeepSeek V4',
    value: 'deepseek-ai/DeepSeek-V4',
    provider: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
  },
  {
    label: 'DeepSeek V4 Pro',
    value: 'deepseek-ai/DeepSeek-V4-Pro',
    provider: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
  },
  {
    label: 'Qwen3 235B (开源旗舰)',
    value: 'Qwen/Qwen3-235B-A22B',
    provider: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
  },
  {
    label: 'GLM-5 Plus (开源)',
    value: 'zhipuai/GLM-5-Plus',
    provider: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
  },

  // ===== 火山方舟 / 豆包 =====（支持分档思考长度）
  {
    label: 'Doubao Seed 2.1 Pro (旗舰)',
    value: 'doubao-seed-2.1-pro',
    provider: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  },
  {
    label: 'Doubao Seed 2.1 Turbo (轻量)',
    value: 'doubao-seed-2.1-turbo',
    provider: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  },
  {
    label: 'Doubao Seed 1.6 (成熟版)',
    value: 'doubao-seed-1.6',
    provider: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  },
  {
    label: 'Doubao Seed 1.6 Flash (极速)',
    value: 'doubao-seed-1.6-flash',
    provider: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  },

  // ===== 腾讯云混元 =====
  {
    label: 'Hunyuan Turbo S (快思考)',
    value: 'hunyuan-turbo-s',
    provider: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
  },
  {
    label: 'Hunyuan Standard (标准)',
    value: 'hunyuan-standard',
    provider: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
  },
  {
    label: 'Hunyuan Lite (免费)',
    value: 'hunyuan-lite',
    provider: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
  },

  // ===== Moonshot / Kimi =====
  {
    label: 'Kimi K2.6 (最新旗舰)',
    value: 'kimi-k2.6',
    provider: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
  },
  {
    label: 'Kimi K2.5',
    value: 'kimi-k2.5',
    provider: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
  },
  {
    label: 'Moonshot v1 Auto (自动上下文)',
    value: 'moonshot-v1-auto',
    provider: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
  },

  // ===== 智谱 GLM =====（GLM-5 用 reasoning_effort 替代标准 thinking 参数）
  {
    label: 'GLM-5.2 (最新开源)',
    value: 'glm-5.2',
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    label: 'GLM-5 Plus (旗舰)',
    value: 'glm-5-plus',
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    label: 'GLM-5 Turbo (工作流优化)',
    value: 'glm-5-turbo',
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
  },
  {
    label: 'GLM-5 Flash (轻量)',
    value: 'glm-5-flash',
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
  },

  // ===== Anthropic Claude =====（原生 API 用 /v1/messages，此处走官方 OpenAI 兼容端点；
  //                              Fable 5 为 Mythos 级旗舰，2026-06-09 发布，曾因出口管制下线后已恢复）
  {
    label: 'Claude Fable 5 (神话级旗舰)',
    value: 'claude-fable-5',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },
  // Claude Opus 4.8 于 2026-05-28 发布，4.7 于 2026-04-16 发布，4.6 于 2026-02-05 发布
  {
    label: 'Claude Opus 4.8 (最新旗舰)',
    value: 'claude-opus-4-8',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },
  {
    label: 'Claude Opus 4.7 (编程增强)',
    value: 'claude-opus-4-7',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },
  {
    label: 'Claude Opus 4.6 (旗舰)',
    value: 'claude-opus-4-6',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },
  {
    label: 'Claude Sonnet 4.5 (均衡)',
    value: 'claude-sonnet-4-5',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },
  {
    label: 'Claude Haiku 4.5 (轻量)',
    value: 'claude-haiku-4-5',
    provider: 'anthropic',
    base_url: 'https://api.anthropic.com/v1/openai/v1',
  },

  // ===== OpenRouter (聚合) =====
  {
    label: 'OpenAI GPT-5.6 Sol',
    value: 'openai/gpt-5.6-sol',
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
  },
  {
    label: 'Anthropic Claude Opus 4.6',
    value: 'anthropic/claude-opus-4.6',
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
  },
  {
    label: 'DeepSeek V4 Pro',
    value: 'deepseek/deepseek-v4-pro',
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
  },
  {
    label: 'Google Gemini 2.5 Pro',
    value: 'google/gemini-2.5-pro',
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
  },

  // ===== Groq (极速推理) =====
  {
    label: 'Llama 3.3 70B Versatile',
    value: 'llama-3.3-70b-versatile',
    provider: 'groq',
    base_url: 'https://api.groq.com/openai/v1',
  },
  {
    label: 'Llama 4 Scout 17B',
    value: 'meta-llama/llama-4-scout-17b-16e-instruct',
    provider: 'groq',
    base_url: 'https://api.groq.com/openai/v1',
  },
];

export function findProvider(value) {
  return MODEL_PROVIDERS.find(provider => provider.value === value) || MODEL_PROVIDERS[0];
}

export function modelPresetsForProvider(providerValue) {
  const scoped = MODEL_PRESETS.filter(preset => preset.provider === providerValue);
  if (!providerValue || providerValue === DEFAULT_AI_PROVIDER) {
    return MODEL_PRESETS;
  }
  return scoped;
}

export function applyProviderPreset(profile) {
  if (!profile) return;
  const provider = findProvider(profile.provider);
  if (provider.base_url) {
    profile.base_url = provider.base_url;
  }
  if (provider.default_model) {
    profile.model = provider.default_model;
  } else if (provider.value !== DEFAULT_AI_PROVIDER) {
    profile.model = '';
  }
  if (typeof provider.thinking_enabled === 'boolean') {
    profile.thinking_enabled = provider.thinking_enabled;
  }
  if (provider.thinking_budget_tokens) {
    profile.thinking_budget_tokens = provider.thinking_budget_tokens;
  }
  // 同步思考深度支持情况
  profile.supports_reasoning_effort = !!provider.supports_reasoning_effort;
  profile.reasoning_effort_levels = provider.reasoning_effort_levels
    ? [...provider.reasoning_effort_levels]
    : [];
  // 若当前 reasoning_effort 不在新厂商支持的档位中，重置为空（让 API 用默认值）
  if (profile.reasoning_effort && !profile.reasoning_effort_levels.includes(profile.reasoning_effort)) {
    profile.reasoning_effort = '';
  }
}

export function applyModelPreset(profile) {
  if (!profile) return;
  const preset = MODEL_PRESETS.find(item => item.value === profile.model);
  if (!preset) return;
  profile.provider = preset.provider || profile.provider || DEFAULT_AI_PROVIDER;
  profile.base_url = preset.base_url;
  if (typeof preset.thinking_enabled === 'boolean') {
    profile.thinking_enabled = preset.thinking_enabled;
  }
  if (preset.thinking_budget_tokens) {
    profile.thinking_budget_tokens = preset.thinking_budget_tokens;
  }
  // 切换模型后，重新同步对应厂商的思考深度支持情况
  const provider = findProvider(profile.provider);
  profile.supports_reasoning_effort = !!provider.supports_reasoning_effort;
  profile.reasoning_effort_levels = provider.reasoning_effort_levels
    ? [...provider.reasoning_effort_levels]
    : [];
  if (profile.reasoning_effort && !profile.reasoning_effort_levels.includes(profile.reasoning_effort)) {
    profile.reasoning_effort = '';
  }
}

// 当前 profile 是否应展示"思考深度"选择器
export function shouldShowReasoningEffort(profile) {
  return !!profile?.thinking_enabled && !!profile?.supports_reasoning_effort
    && Array.isArray(profile.reasoning_effort_levels) && profile.reasoning_effort_levels.length > 0;
}
