import { expect, test } from '@playwright/test';

test('workbench opens the login dialog from the unauthenticated shell', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/workspace/);
  await expect(page.getByText('灵枢').first()).toBeVisible();

  const loginTitle = page.getByText('登录灵枢');
  if (!(await loginTitle.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /未登录/ }).click();
  }

  await expect(loginTitle).toBeVisible();
  await expect(page.getByLabel('用户名')).toBeVisible();
  await expect(page.getByLabel('密码')).toBeVisible();
});
