export type ColumnDef = {
  prop: string;
  label: string;
  width?: number;
  mono?: boolean;
  tag?: Record<string, string>;
  bytes?: boolean;
  seconds?: boolean;
  number?: boolean;
  quota?: string;
  quotaLimit?: string;
};

export const columnsBySection: Record<string, ColumnDef[]> = {
  users: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'username', label: '用户名', width: 130 },
    { prop: 'is_author', label: '作者', width: 90 },
    { prop: 'is_admin', label: '管理员', width: 100 },
    { prop: 'status', label: '状态', width: 110, tag: { active: 'success', disabled: 'danger' } },
    { prop: 'token_count', label: 'Token', width: 100 },
    { prop: 'online_seconds', label: '在线时长', width: 130, seconds: true },
    { prop: 'analysis_count', label: '分析次数', width: 110, number: true },
    { prop: 'ai_total_tokens', label: 'AI Token', width: 120, number: true },
    { prop: 'total_input_chars', label: '输入字数', width: 120, number: true },
    { prop: 'fulltext_book_count', label: '全本作品', width: 110, number: true },
    { prop: 'device_count', label: '设备', width: 100 },
    { prop: 'bookshelf_item_count', label: '书架项', width: 100 },
    { prop: 'created_at', label: '创建时间', width: 170 },
    { prop: 'updated_at', label: '更新时间', width: 170 },
  ],
  devices: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'username', label: '用户', width: 130 },
    { prop: 'user_id', label: 'user_id', width: 100 },
    { prop: 'fingerprint', label: '指纹', width: 220, mono: true },
    { prop: 'device_info', label: '设备信息', width: 220 },
    { prop: 'ip_address', label: 'IP', width: 130 },
    { prop: 'trusted_until', label: '可信到', width: 170 },
    { prop: 'updated_at', label: '更新时间', width: 170 },
  ],
  sync: [
    { prop: 'book_title', label: '作品名', width: 180 },
    { prop: 'username', label: '用户', width: 120 },
    { prop: 'local_version', label: '本地版本', width: 100 },
    { prop: 'remote_version', label: '云端版本', width: 100 },
    { prop: 'sync_state', label: '同步状态', width: 110, tag: { idle: 'info', pending: '', pushing: 'warning', pulling: 'warning', conflict: 'danger', error: 'danger' } },
    { prop: 'last_synced_at', label: '最后同步', width: 170 },
    { prop: 'last_error', label: '错误信息', width: 220 },
  ],
  quotas: [
    { prop: 'username', label: '用户', width: 120 },
    { prop: 'tier', label: '会员等级', width: 110, tag: { free: 'info', basic: '', pro: 'success' } },
    { prop: 'sync_storage_used_bytes', label: '同步容量', width: 160, quota: 'sync_storage_used_bytes', quotaLimit: 'sync_storage_limit_bytes' },
    { prop: 'ai_calls_used', label: 'AI 调用', width: 110 },
    { prop: 'ai_total_tokens', label: 'AI Token', width: 120, number: true },
    { prop: 'total_input_chars', label: '输入字数', width: 120, number: true },
    { prop: 'online_seconds', label: '在线时长', width: 130, seconds: true },
    { prop: 'fulltext_book_count', label: '全本作品', width: 110, number: true },
    { prop: 'ai_calls_limit', label: 'AI 上限', width: 100 },
    { prop: 'book_limit', label: '作品上限', width: 100 },
    { prop: 'device_limit', label: '设备上限', width: 100 },
    { prop: 'expires_at', label: '到期时间', width: 170 },
  ],
  audits: [
    { prop: 'id', label: 'ID', width: 80 },
    { prop: 'admin_username', label: '管理员', width: 130 },
    { prop: 'admin_user_id', label: 'admin_user_id', width: 130 },
    { prop: 'action', label: '动作', width: 110 },
    { prop: 'object_type', label: '对象类型', width: 140 },
    { prop: 'object_id', label: '对象 ID', width: 140 },
    { prop: 'detail', label: '详情', width: 260 },
    { prop: 'created_at', label: '时间', width: 170 },
  ],
  settings: [
    { prop: 'key', label: '键', width: 200, mono: true },
    { prop: 'value_json', label: '值', width: 300 },
    { prop: 'description', label: '说明', width: 200 },
    { prop: 'updated_at', label: '更新时间', width: 170 },
  ],
};
