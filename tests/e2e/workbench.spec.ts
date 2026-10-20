/**
 * 工作台核心链路 E2E — 真实后端（uvicorn + 独立数据目录）+ 前端 dev server。
 *
 * - personal-client P3：登录/登出 UI 与 /api/auth/login、社区页面已剥离，
 *   前端以本地单用户模式免登录直达工作台；本 spec 相应删除登录与社区用例，
 *   保留工作台核心链路（建书/建章/保存/切换）。
 * - 后端本地模式下 require_login 直通，API 调用无需 Authorization 头。
 * - 测试书籍统一使用 `PW-E2E` 前缀 + 唯一后缀，afterEach 通过 API 清理。
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const BOOK_PREFIX = 'PW-E2E';
const RUN_TAG = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;

// ================================================================
// API 辅助（走 vite 代理 → 8787 真实后端）
// ================================================================

async function apiCreateBook(request: APIRequestContext, title: string): Promise<number> {
  const resp = await request.post('/api/workspace/books', { data: { title } });
  expect(resp.ok(), `建书失败: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  return Number(body.item.id);
}

async function apiCreateChapter(request: APIRequestContext, bookId: number, title: string): Promise<number> {
  const resp = await request.post(`/api/workspace/books/${bookId}/chapters`, {
    data: { title },
  });
  expect(resp.ok(), `建章失败: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  const body = await resp.json();
  return Number(body.item.id);
}

async function cleanupE2EBooks(request: APIRequestContext): Promise<void> {
  try {
    const resp = await request.get('/api/workspace/books');
    if (!resp.ok()) return;
    const body = await resp.json();
    for (const book of body.items || []) {
      if (String(book.title || '').startsWith(BOOK_PREFIX)) {
        await request.delete(`/api/workspace/books/${book.id}`);
      }
    }
  } catch (error) {
    console.warn('[cleanup] 清理 PW-E2E 书籍失败（不影响用例判定）:', error);
  }
}

// ================================================================
// UI 辅助
// ================================================================

/** ElMessageBox.prompt 输入并确认。 */
async function confirmMessageBox(page: Page, text: string) {
  await expect(page.locator('.el-message-box')).toBeVisible();
  await page.locator('.el-message-box__input input').fill(text);
  await page.locator('.el-message-box__btns .el-button--primary').click();
}

// ================================================================
// 全局清理
// ================================================================

test.afterEach(async ({ request }) => {
  await cleanupE2EBooks(request);
});

// ================================================================
// 1. 新建作品（欢迎页入口）
// ================================================================

test('从欢迎页新建作品并进入大纲编辑', async ({ page }) => {
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
// 2. 新建分卷与章节
// ================================================================

test('在书籍内新建分卷与章节', async ({ page }) => {
  const bookTitle = `${BOOK_PREFIX}-${RUN_TAG}-分卷章节`;
  const bookId = await apiCreateBook(page.request, bookTitle);

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
// 3. 章节内容保存与刷新持久化
// ================================================================

test('章节写入内容保存后刷新仍在', async ({ page }) => {
  const bookTitle = `${BOOK_PREFIX}-${RUN_TAG}-保存持久化`;
  const bookId = await apiCreateBook(page.request, bookTitle);
  const chapterId = await apiCreateChapter(page.request, bookId, '第一章 持久化');
  // 单行正文：保存时的段落规范化不会改写单行内容，可精确断言
  const content = `E2E 正文 ${RUN_TAG}：工作台保存链路验证。`;

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
// 4. 书籍列表与切换冒烟
// ================================================================

test('书籍树展示与切换作品冒烟', async ({ page }) => {
  const bookA = `${BOOK_PREFIX}-${RUN_TAG}-甲`;
  const bookB = `${BOOK_PREFIX}-${RUN_TAG}-乙`;
  await apiCreateBook(page.request, bookA);
  await apiCreateBook(page.request, bookB);

  await page.goto('/workspace');
  await expect(page.locator('.tree-label', { hasText: bookA }).first()).toBeVisible();
  await expect(page.locator('.tree-label', { hasText: bookB }).first()).toBeVisible();

  // 点击书籍节点 → 打开大纲编辑
  await page.locator('.tree-label', { hasText: bookA }).first().click();
  await expect(page.getByText(`《${bookA}》- 大纲`)).toBeVisible();
  await expect(page.locator('.tree-label', { hasText: bookB }).first()).toBeVisible();

  // 切换到另一本书（SPA 树节点点击 → 打开其大纲）
  await page.locator('.tree-label', { hasText: bookB }).first().click();
  await expect(page.getByText(`《${bookB}》- 大纲`)).toBeVisible();
});
