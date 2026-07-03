export const DEFAULT_AI_PROVIDER = 'custom';
export const DEFAULT_BASE_URL = 'https://api.openai.com/v1';

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
    default_model: 'gpt-4o-mini',
  },
  {
    label: 'DeepSeek',
    value: 'deepseek',
    base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-v4-flash',
    thinking_enabled: false,
  },
  {
    label: '阿里云百炼 / 通义千问',
    value: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    default_model: 'qwen-plus',
  },
  {
    label: '硅基流动',
    value: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
    default_model: 'deepseek-ai/DeepSeek-V3',
  },
  {
    label: '火山方舟 / 豆包',
    value: 'volcengine',
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    default_model: '',
  },
  {
    label: '腾讯云混元',
    value: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
    default_model: 'hunyuan-turbos-latest',
  },
  {
    label: 'Moonshot / Kimi',
    value: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
    default_model: 'moonshot-v1-8k',
  },
  {
    label: '智谱 GLM',
    value: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    default_model: 'glm-4-flash',
  },
  {
    label: 'OpenRouter',
    value: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
    default_model: 'openai/gpt-4o-mini',
  },
  {
    label: 'Groq',
    value: 'groq',
    base_url: 'https://api.groq.com/openai/v1',
    default_model: 'llama-3.3-70b-versatile',
  },
  {
    label: 'PPIO',
    value: 'ppio',
    base_url: 'https://api.ppinfra.com/v3/openai',
    default_model: '',
  },
];

export const MODEL_PRESETS = [
  {
    label: 'GPT-4o mini',
    value: 'gpt-4o-mini',
    provider: 'openai',
    base_url: DEFAULT_BASE_URL,
  },
  {
    label: 'DeepSeek V4 Flash',
    value: 'deepseek-v4-flash',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
    thinking_enabled: false,
  },
  {
    label: 'DeepSeek V4 Pro',
    value: 'deepseek-v4-pro',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
    thinking_enabled: true,
    thinking_budget_tokens: 10000,
  },
  {
    label: 'Qwen Plus',
    value: 'qwen-plus',
    provider: 'dashscope',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    label: 'DeepSeek-V3',
    value: 'deepseek-ai/DeepSeek-V3',
    provider: 'siliconflow',
    base_url: 'https://api.siliconflow.cn/v1',
  },
  {
    label: 'Hunyuan TurboS',
    value: 'hunyuan-turbos-latest',
    provider: 'tencent',
    base_url: 'https://api.hunyuan.cloud.tencent.com/v1',
  },
  {
    label: 'Moonshot v1 8K',
    value: 'moonshot-v1-8k',
    provider: 'moonshot',
    base_url: 'https://api.moonshot.cn/v1',
  },
  {
    label: 'GLM-4 Flash',
    value: 'glm-4-flash',
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
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
}
