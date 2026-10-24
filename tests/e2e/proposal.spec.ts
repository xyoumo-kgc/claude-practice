import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SCRIPTS = path.join(ROOT, '.claude/skills/proposal/scripts');

/**
 * proposal スキルが作ったシーンが、そのまま Web CAD で開けることを確認する。
 * スクリプト側の座標計算と、アプリ側の読み込み仕様がずれたらここで落ちる。
 */
test('proposal スキルが生成したシーンを Web CAD で開ける', async ({ page }) => {
  const workDir = mkdtempSync(path.join(tmpdir(), 'proposal-'));
  const scenePath = path.join(workDir, 'scene.json');
  const estimatePath = path.join(workDir, 'estimate.md');
  const spec = path.join(ROOT, 'tests/fixtures/spec-sample-room.json');

  execFileSync('python3', [path.join(SCRIPTS, 'make_scene.py'), spec, '-o', scenePath]);
  execFileSync('python3', [path.join(SCRIPTS, 'make_estimate.py'), spec, '-o', estimatePath], {
    cwd: SCRIPTS,
  });

  const errors: string[] = [];
  page.on('console', (message) => message.type() === 'error' && errors.push(message.text()));
  page.on('pageerror', (error) => errors.push(String(error)));

  await page.goto('/');
  await page.setInputFiles('#file-input', scenePath);

  await expect(page.locator('#status')).toContainText('14 個のオブジェクトを読み込みました');
  await expect(page.locator('#proposal-project')).toHaveValue('サンプル様邸 1LDK');
  await expect(page.locator('#proposal-customer')).toHaveValue('山田 花子');

  // 自動生成したアングル(全体パース・平面図)が提案書 PDF のページになる
  await expect(page.locator('#view-list')).toContainText('全体パース');
  await expect(page.locator('#view-list')).toContainText('平面図');

  // 見積の下書きも同じスペックから作れている
  const estimate = readFileSync(estimatePath, 'utf-8');
  expect(estimate).toContain('サンプル様邸 1LDK');
  expect(estimate).toContain('床仕上げ');

  expect(errors).toEqual([]);
});
