const { test, expect } = require('@playwright/test');

test('Chromium renders, handles input and captures a screenshot', async ({ page }, testInfo) => {
  await page.route('**/*', route => route.abort());
  await page.setContent('<h1>Browser ready</h1><button onclick="this.textContent=\'Clicked\'">Try it</button>');
  await expect(page.getByRole('heading')).toHaveText('Browser ready');
  await page.getByRole('button', { name: 'Try it' }).click();
  await expect(page.getByRole('button')).toHaveText('Clicked');
  await page.screenshot({ path: testInfo.outputPath('browser-smoke.png') });
});
