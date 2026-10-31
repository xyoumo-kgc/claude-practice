// Claude Code の使用量を ccusage で集計して usage.js に書き出すスクリプト。
// 使い方:  node update-usage.mjs
// 必要なもの: Node.js（npx が使えること）と、ローカルで Claude Code CLI を使った履歴
//   (~/.claude/projects/ の JSONL ログを ccusage が読みます)
//
// ccusage はコミュニティ製ツールのため出力形式が変わることがあります。
// その場合はこのスクリプトの抽出部分を直してください（防御的に書いてあります）。

import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";

// 週ゲージの上限の目安（トークン数）。プランの正確な上限は公開されていないため、
// 何週か運用して「上限に当たった週のトークン数」を入れると %表示になります。
// null のままなら週はトークン数表示になります。
const WEEKLY_TOKEN_LIMIT = null; // 例: 300_000_000

function run(cmd) {
  return execSync(cmd, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 120000 });
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

let block = null, week = null, error = null;

// ── 5時間ブロック ──
try {
  const out = run("npx -y ccusage@latest blocks --json --token-limit max");
  const data = JSON.parse(out);
  const blocks = pick(data, ["blocks", "data"]) || [];
  const active = blocks.find(b => b.isActive) || blocks[blocks.length - 1];
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
  }
} catch (e) {
  error = "blocks: " + String(e.message || e).slice(0, 200);
}

// ── 今週 ──
try {
  const out = run("npx -y ccusage@latest weekly --json");
  const data = JSON.parse(out);
  const rows = pick(data, ["weekly", "data", "rows"]) || [];
  const cur = rows[rows.length - 1];
  if (cur) {
    const tokens = num(pick(cur, ["totalTokens", "tokens"])) ?? 0;
    week = {
      tokens,
      costUSD: num(pick(cur, ["totalCost", "costUSD", "cost"])),
      pct: WEEKLY_TOKEN_LIMIT ? Math.min(100, Math.round((tokens / WEEKLY_TOKEN_LIMIT) * 100)) : null,
    };
  }
} catch (e) {
  error = (error ? error + " / " : "") + "weekly: " + String(e.message || e).slice(0, 200);
}

const now = new Date();
const pad = n => String(n).padStart(2, "0");
const usage = {
  updatedAt: `${now.getFullYear()}/${pad(now.getMonth() + 1)}/${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`,
  block,
  week,
  error,
};

writeFileSync(new URL("./usage.js", import.meta.url),
  "// update-usage.mjs が自動生成（" + usage.updatedAt + "）\nwindow.USAGE = " + JSON.stringify(usage, null, 1) + ";\n");
console.log("usage.js を更新しました:", JSON.stringify(usage));
if (error) console.error("警告:", error);
