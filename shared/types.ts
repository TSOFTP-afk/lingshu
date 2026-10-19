/**
 * 共享类型声明 —— 由 lingshu-app 使用。
 *
 * 设计原则：
 *  - 仅放置通用的、跨页面可复用的类型
 *  - 不放置项目特定的业务类型（如 lingshu-app 的章节/卷类型）
 *  - 保持零运行时依赖，仅类型导出
 *
 * 说明（V5-P3-05 重构）：
 *  - AuthUser / LoginResponse：原 lingshu-app/src/stores/auth.ts 中定义，
 *    通用性强，迁移至 shared。
 *  - ApiError：原 lingshu-app/src/stores/auth.ts 中的私有接口，描述 axios
 *    错误结构，统一抽出。
 *  - ApiResponse<T>：新增的通用响应包装类型。
 *
 * 注意：管理员用户模型（含 role / is_admin 字段）与 AuthUser 形状不同，
 *      不强行复用 AuthUser。
 */

/**
 * 灵枢应用普通登录用户。对应后端 /auth/me 返回的主体。
 * 管理员用户模型字段不同（role / is_admin），不复用此类型。
 */
export interface AuthUser {
  id: number;
  username: string;
  is_author?: number;
  [key: string]: unknown;
}

/**
 * 登录 / 注册接口的响应体。
 */
export interface LoginResponse {
  access_token?: string;
  user?: AuthUser;
  [key: string]: unknown;
}

/**
 * 通用 axios 错误结构。两个项目在 catch 块中均会读取此形状。
 */
export interface ApiError {
  response?: {
    data?: {
      detail?: string | { message?: string; [key: string]: unknown };
    };
    status?: number;
  };
  message?: string;
  [key: string]: unknown;
}

/**
 * 通用 API 响应包装类型。可用于描述后端返回的标准信封结构。
 */
export interface ApiResponse<T = unknown> {
  data?: T;
  message?: string;
  detail?: string;
  [key: string]: unknown;
}
