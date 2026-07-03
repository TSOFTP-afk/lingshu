/**
 * 认证密码处理。
 *
 * 密码只通过 HTTPS 提交给后端，后端使用私有 pepper/salt + bcrypt 处理。
 * 旧版公开 /api/auth/password-params 派生参数的客户端预哈希已停用。
 */
export async function hashPasswordClient(password: string): Promise<string> {
  return password;
}
