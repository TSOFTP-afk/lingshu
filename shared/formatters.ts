/**
 * 通用格式化函数 —— 由 lingshu-app 与 cloud-admin 共享。
 *
 * 设计原则：
 *  - 纯函数，无 Vue / Element Plus / axios 等运行时依赖
 *  - 无副作用，可直接在模板与单元测试中使用
 *  - 不依赖任何项目特定的类型（如 Row），仅使用基础类型
 *
 * 来源：原 cloud-admin/src/composables/useApi.ts 中的内嵌格式化函数，
 *      因 lingshu-app 也存在等价实现（如 BookEntryDialog.vue 的 formatSize），
 *      统一抽取以消除重复（V5-P3-05）。
 */

/**
 * 将数字（或可转换为数字的字符串）格式化为千分位整数字符串。
 * 非有限值统一返回 '0'。
 */
export function formatNumber(value: number | string | undefined | null): string {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return '0';
  return Math.round(num).toLocaleString();
}

/**
 * 将任意值格式化为可展示的字符串。
 * - null / undefined / ''  -> '-'
 * - 对象                    -> JSON 字符串
 * - 其他                    -> String(value)
 */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * 将字节数格式化为带单位的可读字符串（B / KB / MB / GB / TB）。
 * - null / undefined -> '-'
 * - 0                -> '0 B'
 * - B 级别保留 0 位小数，KB 及以上保留 1 位小数
 */
export function formatBytes(bytes: number | undefined | null): string {
  if (!bytes && bytes !== 0) return '-';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * 将秒数格式化为中文可读时长（天 / 小时 / 分钟 / 秒）。
 * 负值会被截断为 0。
 */
export function formatDuration(seconds: number | string | undefined | null): string {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}天 ${hours}小时`;
  if (hours > 0) return `${hours}小时 ${minutes}分钟`;
  if (minutes > 0) return `${minutes}分钟`;
  return `${total}秒`;
}
