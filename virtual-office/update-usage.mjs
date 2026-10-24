// Claude Code の使用量を ccusage で集計するモジュール兼スクリプト。
//   単体実行:  node update-usage.mjs   → usage.js に書き出し（file:// で開く用）
//   server.mjs からは collectUsage() を import して5分おきに呼びます。
// 必要なもの: Node.js（npx が使えること）と、ローカルで Claude Code を使った履歴
//   (~/.claude/projects/ の JSONL ログを ccusage が読みます)
//
// ccusage はコミュニティ製ツールのため出力形式が変わることがあります。
// その場合はこのスクリプトの抽出部分を直してください（防御的に書いてあります）。

import { exec } from "node:child_process";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execAsync = promisify(exec);

// 週ゲージの上限の目安（トークン数）。プランの正確な上限は公開されていないため、
// 何週か運用して「上限に当たった週のトークン数」を入れると %表示になります。
// null のままなら週はトークン数表示になります。
const WEEKLY_TOKEN_LIMIT = null; // 例: 300_000_000

async function runJson(cmd) {
  const { stdout } = await execAsync(cmd, { timeout: 120000, maxBuffer: 32 * 1024 * 1024, windowsHide: true });
  return JSON.parse(stdout);
}
function num(v) {
  return typeof v === "number" && isFinite(v) ? v : null;
}
// オブジェクトから最初に見つかったキーの値を返す（ccusage の版差を吸収）
function pick(obj, keys) {
  if (!obj) return null;
  for (const k of keys) if (obj[k] != null) return obj[k];
  return null;
}
function stamp(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export async function collectUsage() {
  let block = null, week = null, error = null;

  // ── 5時間ブロック ──
  try {
    const data = await runJson("npx -y ccusage@latest blocks --json --token-limit max");
    const blocks = pick(data, ["blocks", "data"]) || [];
    const active = blocks.find(b => b.isActive);
    if (active) {
      const tokens = num(pick(active, ["totalTokens", "tokens"])) ?? 0;
      const limitStatus = pick(active, ["tokenLimitStatus", "limitStatus"]);
      const limit = num(pick(limitStatus || {}, ["limit", "tokenLimit"]));
      block = {
        tokens,
        limitTokens: limit,
        pct: limit ? Math.min(100, Math.round((tokens / limit) * 100)) : null,
        resetAt: pick(active, ["endTime", "end"]),
        costUSD: num(pick(active, ["costUSD", "totalCost", "cost"])),
      };
    } else {
      // 今の5時間枠ではまだ何も使っていない
      block = { tokens: 0, limitTokens: null, pct: 0, resetAt: null, costUSD: 0 };
    }
  } catch (e) {
    error = "blocks: " + String(e.message || e).slice(0, 200);
  }

  // ── 今週 ──
  try {
    const data = await runJson("npx -y ccusage@latest weekly --json");
    const rows = pick(data, ["weekly", "data", "rows"]) || [];
    const cur = rows[rows.length - 1];
    const start = cur && Date.parse(pick(cur, ["period", "week", "startDate"]));
    const isThisWeek = cur && (!isFinite(start) || Date.now() - start < 7 * 24 * 3600 * 1000);
    const tokens = isThisWeek ? (num(pick(cur, ["totalTokens", "tokens"])) ?? 0) : 0;
    week = {
      tokens,
      costUSD: isThisWeek ? num(pick(cur, ["totalCost", "costUSD", "cost"])) : 0,
      pct: WEEKLY_TOKEN_LIMIT ? Math.min(100, Math.round((tokens / WEEKLY_TOKEN_LIMIT) * 100)) : null,
    };
  } catch (e) {
    error = (error ? error + " / " : "") + "weekly: " + String(e.message || e).slice(0, 200);
  }

  return { updatedAt: stamp(new Date()), block, week, error };
}

export function writeUsageFile(usage) {
  writeFileSync(new URL("./usage.js", import.meta.url),
    "// update-usage.mjs が自動生成（" + usage.updatedAt + "）\nwindow.USAGE = " + JSON.stringify(usage, null, 1) + ";\n");
}

// 単体実行されたときだけ usage.js を書き出す
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const usage = await collectUsage();
  writeUsageFile(usage);
  console.log("usage.js を更新しました:", JSON.stringify(usage));
  if (usage.error) console.error("警告:", usage.error);
}
