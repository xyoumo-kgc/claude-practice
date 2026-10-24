// バーチャルオフィスのインストーラー
//   node install.mjs              → フック登録＋（Windowsなら）ログオン時の自動起動を登録
//   node install.mjs --uninstall  → 両方とも取り除く
//
// ~/.claude/settings.json は書き換える前に settings.json.bak-virtual-office へバックアップします。
// 何度実行しても重複しません（以前登録した office-hook.mjs の行を消してから入れ直します）。

import { readFileSync, writeFileSync, existsSync, mkdirSync, copyFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(DIR, "office-hook.mjs").replace(/\\/g, "/"); // cmd でも bash でも通るようにスラッシュ区切り
const MARK = "office-hook.mjs";
const SETTINGS = path.join(os.homedir(), ".claude", "settings.json");
const EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification", "Stop", "SubagentStop", "PreCompact", "SessionEnd"];
const TOOL_EVENTS = new Set(["PreToolUse", "PostToolUse"]);
const uninstall = process.argv.includes("--uninstall");

/* ── 1. Claude Code のフック ── */
let settings = {};
if (existsSync(SETTINGS)) {
  const raw = readFileSync(SETTINGS, "utf8");
  try {
    settings = raw.trim() ? JSON.parse(raw) : {};
  } catch (e) {
    console.error(`[中止] ${SETTINGS} が JSON として読めません。手で直してから再実行してください。\n  ${e.message}`);
    process.exit(1);
  }
  copyFileSync(SETTINGS, SETTINGS + ".bak-virtual-office");
} else {
  mkdirSync(path.dirname(SETTINGS), { recursive: true });
}

const isOurs = h => String((h && h.command) || "").includes(MARK);
const hooks = settings.hooks && typeof settings.hooks === "object" ? settings.hooks : {};
for (const ev of Object.keys(hooks)) {
  if (!Array.isArray(hooks[ev])) continue;
  hooks[ev] = hooks[ev].flatMap(g => {
    if (!g || !Array.isArray(g.hooks) || !g.hooks.some(isOurs)) return [g]; // 他のフックには触らない
    const rest = g.hooks.filter(h => !isOurs(h));
    return rest.length ? [{ ...g, hooks: rest }] : [];
  });
  if (!hooks[ev].length) delete hooks[ev];
}
if (!uninstall) {
  for (const ev of EVENTS) {
    const group = { hooks: [{ type: "command", command: `node "${HOOK}"`, timeout: 5 }] };
    if (TOOL_EVENTS.has(ev)) group.matcher = "*";
    (hooks[ev] ||= []).push(group);
  }
}
if (Object.keys(hooks).length) settings.hooks = hooks;
else delete settings.hooks;
writeFileSync(SETTINGS, JSON.stringify(settings, null, 2) + "\n");
console.log(uninstall ? `フックを削除しました: ${SETTINGS}` : `フックを登録しました: ${SETTINGS}（${EVENTS.length}種類のイベント）`);

/* ── 2. ログオン時の自動起動（Windows のスタートアップフォルダ。管理者権限不要） ── */
if (process.platform === "win32" && process.env.APPDATA) {
  const startup = path.join(process.env.APPDATA, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "VirtualOffice.cmd");
  if (uninstall) {
    rmSync(startup, { force: true });
    console.log("自動起動を解除しました");
  } else {
    writeFileSync(startup, [
      "@echo off",
      `cd /d "${DIR}"`,
      "powershell -NoProfile -WindowStyle Hidden -Command \"Start-Process -FilePath node -ArgumentList 'server.mjs' " +
        "-WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput server.log -RedirectStandardError server.err.log\"",
      "",
    ].join("\r\n"));
    console.log(`ログオン時の自動起動を登録しました: ${startup}`);
  }
}
