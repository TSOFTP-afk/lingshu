/**
 * 工作台核心链路 E2E — 真实后端（uvicorn + 独立种子库）+ 前端 dev server。
 *
 * - 种子账号由 tools/seed_test_env.py 在 playwright.config.ts 的 webServer 阶段创建
 *   （默认 e2e_writer / e2e_pass_123，数据目录 data/e2e_seed，绝不碰生产 novels.db）。
 * - 除登录失败/成功用例外，其余用例通过注入 token（localStorage['lingshu_token_web']）
 *   进入已登录态，避免触发后端 /api/auth/login 的 5 次/分钟限流。
 * - 测试书籍统一使用 `PW-E2E` 前缀 + 唯一后缀，afterEach 通过 API 清理。
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const SEED_USER = process.env.LINGSHU_E2E_USER || 'e2e_writer';
const SEED_PASS = process.env.LINGSHU_E2E_PASS || 'e2e_pass_123';
const BOOK_PREFIX = 'PW-E2E';
const RUN_TAG = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
const WEB_TOKEN_KEY = 'lingshu_token_web';

let sharedToken = '';

// ================================================================
// API 辅助（走 vite 代理 → 8787 真实后端）
// ================================================================

async function apiLogin(request: APIRequestContext, username = SEED_USER, password = SEED_PASS): Promise<string> {
  const resp = await request.post('/api/auth/login', { data: { username, password } });
  expect(resp.ok(), `登录失败: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  expect(body.access_token, '登录响应缺少 access_token').toBeTruthy();
  return body.access_token as string;
}

const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` });

async function apiCreateBook(request: APIRequestContext, token: string, title: string): Promise<number> {
  const resp = await request.post('/api/workspace/books', { data: { title }, headers: authHeaders(token) });
  expect(resp.ok(), `建书失败: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  return Number(body.item.id);
}

async function apiCreateChapter(
  request: APIRequestContext,
  token: string,
  bookId: number,
  title: string,
): Promise<number> {
  const resp = await request.post(`/api/workspace/books/${bookId}/chapters`, {
    data: { title },
    headers: authHeaders(token),
  });
  expect(resp.ok(), `建章失败: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  return Number(body.item.id);
}

async function cleanupE2EBooks(request: APIRequestContext, token: string): Promise<void> {
  try {
    const resp = await request.get('/api/workspace/books', { headers: authHeaders(token) });
    if (!resp.ok()) return;
    const body = await resp.json();
    for (const book of body.items || []) {
      if (String(book.title || '').startsWith(BOOK_PREFIX)) {
        await request.delete(`/api/workspace/books/${book.id}`, { headers: authHeaders(token) });
      }
    }
  } catch (error) {
    console.warn('[cleanup] 清理 PW-E2E 书籍失败（不影响用例判定）:', error);
  }
}

// ================================================================
// UI 辅助
// ================================================================

/** 进入未登录工作台并打开登录框（登录框可能自动弹出）。 */
async function openLoginDialog(page: Page) {
  await page.goto('/');
  await expect(page).toHaveURL(/\/workspace/);
  const dialog = page.locator('.login-dialog');
  if (!(await dialog.isVisible().catch(() => false))) {
    await page.locator('button.account-chip').click();
  }
  await expect(page.getByText('登录灵枢')).toBeVisible();
  return dialog;
}

/** 通过种子凭据完成 UI 登录。 */
async function uiLogin(page: Page, username = SEED_USER, password = SEED_PASS) {
  const dialog = await openLoginDialog(page);
  await page.getByLabel('用户名').fill(username);
  await page.getByLabel('密码').fill(password);
  await dialog.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByText('登录成功')).toBeVisible();
}

/** 注入 token 直接进入已登录态（绕开登录接口限流）。 */
async function loginViaToken(page: Page, token: string) {
  await page.addInitScript(
    ({ key, value }) => {
      localStorage.setItem(key, value);
    },
    { key: WEB_TOKEN_KEY, value: token },
  );
}

/** ElMessageBox.prompt 输入并确认。 */
async function confirmMessageBox(page: Page, text: string) {
  await expect(page.locator('.el-message-box')).toBeVisible();
  await page.locator('.el-message-box__input input').fill(text);
  await page.locator('.el-message-box__btns .el-button--primary').click();
}

// ================================================================
// 全局准备与清理
// ================================================================

test.beforeAll(async ({ request }) => {
  sharedToken = await apiLogin(request);
});

test.afterEach(async ({ request }) => {
  await cleanupE2EBooks(request, sharedToken);
});

// ================================================================
// 1. 未登录外壳与登录框渲染
// ================================================================

test('未登录访问工作台时展示登录框', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/workspace/);
  await expect(page.getByText('灵枢').first()).toBeVisible();

  const loginTitle = page.getByText('登录灵枢');
  if (!(await loginTitle.isVisible().catch(() => false))) {
    await page.locator('button.account-chip').click();
  }

  await expect(loginTitle).toBeVisible();
  await expect(page.getByLabel('用户名')).toBeVisible();
  await expect(page.getByLabel('密码')).toBeVisible();
  await expect(page.locator('.login-dialog').getByRole('button', { name: '登录', exact: true })).toBeVisible();
  await expect(page.locator('.login-dialog').getByRole('button', { name: '取消' })).toBeVisible();
});

// ================================================================
// 2. 登录框空表单校验
// ================================================================

test('登录框空表单提交时提示输入用户名和密码', async ({ page }) => {
  await openLoginDialog(page);

  // 两个都为空 → 提示输入用户名
  await page.locator('.login-dialog').getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByText('请输入用户名')).toBeVisible();

  // 只填用户名 → 提示输入密码
  await page.getByLabel('用户名').fill(`${BOOK_PREFIX}-empty`);
  await page.locator('.login-dialog').getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByText('请输入密码')).toBeVisible();

  // 登录框保持打开
  await expect(page.getByText('登录灵枢')).toBeVisible();
});

// ================================================================
// 3. 错误凭据登录失败
// ================================================================

test('错误凭据登录失败并展示错误提示', async ({ page }) => {
  const dialog = await openLoginDialog(page);
  await page.getByLabel('用户名').fill(`${BOOK_PREFIX}-ghost`);
  await page.getByLabel('密码').fill('wrong-pass-123');
  await dialog.getByRole('button', { name: '登录', exact: true }).click();

  await expect(page.getByText('用户名或密码错误').first()).toBeVisible();
  // 登录失败后对话框不关闭
  await expect(page.getByText('登录灵枢')).toBeVisible();
});

// ================================================================
// 4. 种子账号登录成功
// ================================================================

test('种子账号登录成功后展示账号名', async ({ page }) => {
  await uiLogin(page);

  // 对话框关闭、侧栏账号名切换为种子用户名
  await expect(page.getByText('登录灵枢')).toBeHidden();
  await expect(page.locator('.account-name')).toHaveText(SEED_USER);
});

// ================================================================
// 5. 登出
// ================================================================

test('登录后可通过账号菜单退出登录', async ({ page }) => {
  await uiLogin(page);
  await expect(page.locator('.account-name')).toHaveText(SEED_USER);

  await page.locator('button.account-chip').click();
  await page.getByText('退出登录').click();
  await expect(page.getByText('已退出登录')).toBeVisible();
  await expect(page.locator('button.account-chip')).toBeVisible();
  await expect(page.locator('.account-name')).toHaveText('未登录');
});

// ================================================================
// 6. 新建作品（欢迎页入口）
// ================================================================

test('从欢迎页新建作品并进入大纲编辑', async ({ page }) => {
  await loginViaToken(page, sharedToken);
  await page.goto('/');
  await expect(page.getByText('开始新的创作项目')).toBeVisible();

  const title = `${BOOK_PREFIX}-${RUN_TAG}-欢迎页建书`;
  await page.getByRole('button', { name: '新建作品' }).click();
  await expect(page.getByText('作品管理')).toBeVisible();
  await page.getByPlaceholder('输入作品名称').fill(title);
  await page.getByRole('button', { name: '创建作品' }).click();

  await expect(page.getByText('作品已创建')).toBeVisible();
  // 建书后自动打开大纲编辑器
  await expect(page.getByText(`《${title}》- 大纲`)).toBeVisible();
  // 左侧书籍树出现新书
  await expect(page.locator('.tree-label', { hasText: title }).first()).toBeVisible();
});

// ================================================================
// 7. 新建分卷与章节
// ================================================================

test('在书籍内新建分卷与章节', async ({ page }) => {
  const bookTitle = `${BOOK_PREFIX}-${RUN_TAG}-分卷章节`;
  const bookId = await apiCreateBook(page.request, sharedToken, bookTitle);

  await loginViaToken(page, sharedToken);
  await page.goto(`/workspace/books/${bookId}`);
  await expect(page.locator('.tree-label', { hasText: bookTitle }).first()).toBeVisible();

  // 新建分卷（LibraryPanel 顶栏第 3 个图标按钮：新建分卷）
  await page.locator('.header-action').nth(2).click();
  await confirmMessageBox(page, '第一卷');
  await expect(page.getByText('卷级工作区')).toBeVisible();
  await expect(page.locator('.tree-label', { hasText: '第一卷' }).first()).toBeVisible();

  // 新建章节（卷级工作区「新建章节」按钮）
  await page.getByRole('button', { name: '新建章节' }).click();
  await confirmMessageBox(page, '第一章 网页测试');
  await expect(page.getByText('第一章 网页测试').first()).toBeVisible();
  // 章节编辑器出现
  await expect(page.locator('.content-editor-wrapper')).toBeVisible();
});

// ================================================================
// 8. 章节内容保存与刷新持久化
// ================================================================

test('章节写入内容保存后刷新仍在', async ({ page }) => {
  const bookTitle = `${BOOK_PREFIX}-${RUN_TAG}-保存持久化`;
  const bookId = await apiCreateBook(page.request, sharedToken, bookTitle);
  const chapterId = await apiCreateChapter(page.request, sharedToken, bookId, '第一章 持久化');
  // 单行正文：保存时的段落规范化不会改写单行内容，可精确断言
  const content = `E2E 正文 ${RUN_TAG}：工作台保存链路验证。`;

  await loginViaToken(page, sharedToken);
  await page.goto(`/workspace/books/${bookId}?chapter=${chapterId}`);
  await expect(page.locator('.content-editor-wrapper')).toBeVisible();

  // 进入全屏编辑对话框并写入内容
  await page.getByRole('button', { name: '编辑' }).first().click();
  const editDialog = page.locator('.chapter-edit-dialog');
  await expect(editDialog).toBeVisible();
  const textarea = editDialog.locator('textarea.content-textarea');
  await textarea.fill(content);
  await editDialog.getByRole('button', { name: '保存' }).click();
  await expect(page.getByText('已保存').first()).toBeVisible();
  await editDialog.getByRole('button', { name: '关闭' }).click();

  // 刷新后重新打开章节，内容仍在（真实后端持久化）
  await page.reload();
  await page.goto(`/workspace/books/${bookId}?chapter=${chapterId}`);
  await expect(page.locator('.content-editor-wrapper')).toBeVisible();
  await expect(page.locator('.content-textarea')).toHaveValue(content);
});

// ================================================================
// 9. 书籍列表与工作台切换冒烟
// ================================================================

test('书籍树展示、切换作品与导航冒烟', async ({ page }) => {
  const bookA = `${BOOK_PREFIX}-${RUN_TAG}-甲`;
  const bookB = `${BOOK_PREFIX}-${RUN_TAG}-乙`;
  const bookAId = await apiCreateBook(page.request, sharedToken, bookA);
  await apiCreateBook(page.request, sharedToken, bookB);

  await loginViaToken(page, sharedToken);
  await page.goto('/workspace');
  await expect(page.locator('.tree-label', { hasText: bookA }).first()).toBeVisible();
  await expect(page.locator('.tree-label', { hasText: bookB }).first()).toBeVisible();

  // 点击书籍节点 → 打开大纲编辑
  await page.locator('.tree-label', { hasText: bookA }).first().click();
  await expect(page.getByText(`《${bookA}》- 大纲`)).toBeVisible();

  // 导航到卡片社区再返回工作台，书籍树仍在
  await page.getByRole('button', { name: '卡片社区', exact: true }).click();
  await expect(page).toHaveURL(/\/community/);
  await page.getByRole('button', { name: '工作台', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace/);
  await expect(page.locator('.tree-label', { hasText: bookB }).first()).toBeVisible();

  // 切换到另一本书（SPA 树节点点击 → 打开其大纲）
  await page.locator('.tree-label', { hasText: bookB }).first().click();
  await expect(page.getByText(`《${bookB}》- 大纲`)).toBeVisible();
});
