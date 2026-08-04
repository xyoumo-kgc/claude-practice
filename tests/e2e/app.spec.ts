import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

/** コンソールエラーを集める(WebGL 系の描画エラーもここで拾える) */
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => message.type() === 'error' && errors.push(message.text()));
  page.on('pageerror', (error) => errors.push(String(error)));
  return errors;
}

/** 「保存」を押してダウンロードされたシーン JSON を読む */
async function saveScene(page: Page): Promise<any> {
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#save')]);
  return JSON.parse(readFileSync(await download.path(), 'utf-8'));
}

test('起動してコンソールエラーが出ない', async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto('/');
  await expect(page.locator('#status')).toContainText('準備完了');
  expect(errors).toEqual([]);
});

test('部屋を配置して Undo で戻せる', async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto('/');

  await page.click('button[data-shape="room"]');
  await expect(page.locator('#status')).toContainText('部屋を配置');

  const viewport = page.locator('#viewport');
  await viewport.click({ position: { x: 500, y: 450 } });
  await expect(page.locator('#status')).toContainText('を追加しました');
  await page.keyboard.press('Escape');

  const afterAdd = await saveScene(page);
  expect(afterAdd.objects.filter((o: any) => o.type === 'room')).toHaveLength(1);

  await page.keyboard.press('Control+z');
  const afterUndo = await saveScene(page);
  expect(afterUndo.objects).toHaveLength(0);
  expect(errors).toEqual([]);
});

test('サンプルシーンを読み込み、保存でラウンドトリップできる', async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto('/');

  await page.setInputFiles('#file-input', path.join(ROOT, 'examples/sample-room.json'));
  await expect(page.locator('#status')).toContainText('14 個のオブジェクトを読み込みました');

  // 提案書情報と保存アングルも復元される
  await expect(page.locator('#proposal-project')).toHaveValue('サンプル様邸 1LDK');
  await expect(page.locator('#proposal-customer')).toHaveValue('山田 花子');

  const saved = await saveScene(page);
  const original = JSON.parse(readFileSync(path.join(ROOT, 'examples/sample-room.json'), 'utf-8'));
  expect(saved.format).toBe('web-cad');
  expect(saved.version).toBe(4);
  expect(saved.objects).toHaveLength(original.objects.length);
  expect(saved.views.map((v: any) => v.name)).toEqual(original.views.map((v: any) => v.name));
  expect(saved.meta).toEqual(original.meta);

  // 部屋の寸法(m)が保存形式で保たれている
  const ldk = saved.objects.find((o: any) => o.name === 'LDK');
  expect(ldk.params).toEqual({ width: 4.5, depth: 4, height: 2.4 });
  expect(errors).toEqual([]);
});

test('平面図モードに切り替えられる', async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto('/');
  await page.setInputFiles('#file-input', path.join(ROOT, 'examples/sample-room.json'));

  await page.click('#plan-toggle');
  await expect(page.locator('#status')).toContainText('平面図モード');
  await expect(page.locator('#plan-toggle')).toHaveClass(/active/);

  await page.click('#plan-toggle');
  await expect(page.locator('#status')).toContainText('3D ビュー');
  expect(errors).toEqual([]);
});

test('保存アングルから提案書 PDF を出力できる', async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto('/');
  await page.setInputFiles('#file-input', path.join(ROOT, 'examples/sample-room.json'));
  await expect(page.locator('#status')).toContainText('読み込みました');

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 45_000 }),
    page.click('#export-pdf'),
  ]);
  const pdf = readFileSync(await download.path());

  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  // 表紙 + 保存アングル 3 枚 = 4 ページ
  expect(pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g)?.length).toBe(4);
  await expect(page.locator('#status')).toContainText('提案書 PDF を出力しました');
  expect(errors).toEqual([]);
});
