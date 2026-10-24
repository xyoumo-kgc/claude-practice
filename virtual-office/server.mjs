// バーチャルオフィスのリアルタイムサーバー（依存パッケージなし）
//   起動:  node server.mjs   → http://127.0.0.1:4649 を開く
//
// しくみ:
//   Claude Code のフック → office-hook.mjs → POST /hook → ここで社員の状態に変換
//   → SSE (/events) でブラウザへ即時配信。使用量は ccusage で5分おきに集計して同時に配信。
//
// 安全のため 127.0.0.1 だけで待ち受け、Host ヘッダーも localhost 以外は拒否します。

import http from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { collectUsage } from "./update-usage.mjs";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.VIRTUAL_OFFICE_PORT) || 4649;
const STATE_FILE = path.join(DIR, "state.json");

const USAGE_INTERVAL = 5 * 60 * 1000;      // 使用量の集計間隔
const IDLE_TO_REST = 3 * 60 * 1000;        // 手が空いて3分たつと休憩室へ
const STUCK_MS = 10 * 60 * 1000;           // Esc で中断すると Stop が来ないので、10分無音の「作業中」は解除
const SUB_STUCK_MS = 30 * 60 * 1000;       // サブエージェントの作業中も30分無音なら解除
const SESSION_GONE_MS = 3 * 60 * 60 * 1000; // 3時間無音のセッションは退勤扱い

/* ───────── 社員名簿 ───────── */
const ROSTER = [
  { id: "main", name: "Claude", role: "窓口/実装", room: "hq", hair: "#31405e", cloth: "#c85a4a", chat: true },
  { id: "Plan", name: "Plan", role: "設計担当", room: "hq", hair: "#3d4460", cloth: "#5a6acf" },
  { id: "Explore", name: "Explore", role: "調査担当", room: "hq", hair: "#2f6b4f", cloth: "#e0a53a" },
  { id: "general-purpose", name: "general-purpose", role: "何でも屋", room: "hq", hair: "#7a4a2c", cloth: "#3fae6a" },
  { id: "claude-code-guide", name: "code-guide", role: "Claude Code案内", room: "hq", hair: "#8f5d9e", cloth: "#7f6ad4" },
  { id: "statusline-setup", name: "statusline", role: "環境整備", room: "env", hair: "#4a5568", cloth: "#2fae9e" },
];
// 名簿にないサブエージェント（自作エージェントなど）は新入社員として自動で席を用意
const NEWBIE_COLORS = [["#5b3a29", "#d9534f"], ["#2d3e50", "#1abc9c"], ["#6d4c41", "#f39c12"], ["#37474f", "#8e44ad"]];

const emps = new Map();
const sessions = new Map();
let notes = [];
let logs = [];
let usage = null;

for (const r of ROSTER) emps.set(r.id, { ...r, now: "", done: "", next: "", doneCount: 0, doneDate: "" });

function emp(id) {
  if (!emps.has(id)) {
    const [hair, cloth] = NEWBIE_COLORS[(emps.size - ROSTER.length) % NEWBIE_COLORS.length];
    emps.set(id, { id, name: id, role: "新入社員", room: "hq", hair, cloth, now: "", done: "", next: "", doneCount: 0, doneDate: "", newbie: true });
    log(`🎉 新入社員 ${id} が入社しました`);
  }
  return emps.get(id);
}

/* ───────── 永続化（再起動しても「きょうの完了」や掲示板を覚えておく） ───────── */
function loadState() {
  if (!existsSync(STATE_FILE)) return;
  try {
    const s = JSON.parse(readFileSync(STATE_FILE, "utf8"));
    for (const [id, v] of Object.entries(s.emps || {})) {
      const e = v.newbie ? emp(id) : emps.get(id);
      if (e) Object.assign(e, { done: v.done || "", next: v.next || "", doneCount: v.doneCount || 0, doneDate: v.doneDate || "" });
    }
    notes = Array.isArray(s.notes) ? s.notes : [];
    logs = Array.isArray(s.logs) ? s.logs : [];
  } catch (e) {
    console.error("state.json の読み込みに失敗（無視して続行）:", e.message);
  }
}
let saveTimer = null;
function saveSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const out = { emps: {}, notes, logs: logs.slice(-30) };
    for (const e of emps.values()) out.emps[e.id] = { done: e.done, next: e.next, doneCount: e.doneCount, doneDate: e.doneDate, newbie: !!e.newbie };
    try { writeFileSync(STATE_FILE, JSON.stringify(out, null, 1)); } catch (err) { console.error("state.json の保存に失敗:", err.message); }
  }, 2000);
}

/* ───────── ユーティリティ ───────── */
function short(s, n) {
  if (!s) return "";
  s = String(s).replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n) + "…" : s;
}
const baseName = p => (p ? String(p).split(/[\\/]/).filter(Boolean).pop() || "" : "");
const today = () => new Date().toDateString();
function hhmm(t = new Date()) {
  return String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0");
}
function log(text) {
  logs.push({ t: hhmm(), text });
  if (logs.length > 60) logs = logs.slice(-30);
}
function finish(e, text) {
  const d = today();
  e.doneCount = (e.doneDate === d ? e.doneCount : 0) + 1;
  e.doneDate = d;
  e.done = text || e.done;
}
function hostOf(url) {
  try { return new URL(url).host; } catch { return url || ""; }
}
function describeTool(tool, ti) {
  switch (tool) {
    case "Read": return `資料を読んでいる：${baseName(ti.file_path)}`;
    case "Edit": case "MultiEdit": case "Write": case "NotebookEdit": return `書いている：${baseName(ti.file_path)}`;
    case "Bash": case "PowerShell": return `コマンド実行：${short(ti.description || ti.command, 28)}`;
    case "Grep": case "Glob": return `探している：${short(ti.pattern, 28)}`;
    case "WebFetch": case "WebSearch": return `Webで調べ物：${short(ti.query || hostOf(ti.url), 28)}`;
    case "Skill": return `スキル「${ti.skill || "?"}」を使用中`;
  }
  const m = /^mcp__(.+?)__(.+)$/.exec(tool || "");
  if (m) return `${m[1]} で ${m[2]}`;
  return `${tool || "ツール"} を使用中`;
}
const isAgentTool = t => t === "Task" || t === "Agent";
const noteState = st => (st === "in_progress" ? "doing" : st === "completed" ? "done" : "todo");
function trimNotes() {
  while (notes.length > 12) {
    const i = notes.findIndex(n => n.state === "done");
    notes.splice(i >= 0 ? i : 0, 1);
  }
}

/* ───────── フックイベント → 社員の状態 ───────── */
function onHook(ev) {
  const now = Date.now();
  const sid = ev.session_id || "default";
  const project = baseName(ev.cwd);
  let s = sessions.get(sid);
  if (!s) {
    s = { project, working: false, waiting: false, now: "", task: "", lastEvent: now };
    sessions.set(sid, s);
    if (ev.hook_event_name !== "SessionStart" && ev.hook_event_name !== "SessionEnd") log(`☀ Claude が出社しました（${project}）`);
  }
  s.lastEvent = now;
  if (project) s.project = project;
  const main = emps.get("main");
  main.lastActive = now;
  main.summonedAt = 0;
  const ti = ev.tool_input || {};
  const tool = ev.tool_name || "";

  switch (ev.hook_event_name) {
    case "SessionStart":
      s.now = "出社しました";
      if (ev.source !== "compact") log(`☀ Claude が出社しました（${s.project}）`);
      break;

    case "UserPromptSubmit":
      s.working = true; s.waiting = false;
      s.task = short(ev.prompt, 40) || "指示対応";
      s.now = `社長の指示に対応中「${short(ev.prompt, 24)}」`;
      log(`📣 社長から指示「${short(ev.prompt, 30)}」`);
      break;

    case "PreToolUse":
      s.working = true; s.waiting = false;
      if (ev.agent_type && !isAgentTool(tool) && emps.has(ev.agent_type)) {
        // サブエージェントの中で動いたツール → その社員の「いま」を更新（メインはそのまま）
        const e = emps.get(ev.agent_type);
        e.lastActive = now;
        if (e.active > 0) e.doing = describeTool(tool, ti);
      } else if (isAgentTool(tool)) {
        const e = emp(ti.subagent_type || "general-purpose");
        e.active = (e.active || 0) + 1;
        if (ti.run_in_background) e.bg = (e.bg || 0) + 1;
        e.lastActive = now; e.summonedAt = 0;
        e.task = short(ti.description, 40) || "依頼対応";
        e.doing = "";
        s.now = `${e.name} に依頼中「${short(ti.description, 22)}」`;
        log(`🏃 ${e.name} 出動「${short(ti.description, 30)}」`);
      } else if (tool === "TodoWrite" && Array.isArray(ti.todos)) {
        notes = ti.todos.map(t => ({ t: t.content, state: noteState(t.status) }));
        trimNotes();
        const doing = ti.todos.find(t => t.status === "in_progress");
        const next = ti.todos.find(t => t.status === "pending");
        if (doing) s.now = short(doing.activeForm || doing.content, 40);
        main.next = next ? next.content : "";
      } else if (tool === "TaskUpdate" && ti.taskId != null) {
        const n = notes.find(x => String(x.id) === String(ti.taskId));
        if (n && ti.status === "deleted") notes = notes.filter(x => x !== n);
        else if (n && ti.status) n.state = noteState(ti.status);
        if (n && ti.status === "in_progress") s.now = short(n.t, 40);
      } else {
        s.now = describeTool(tool, ti);
      }
      break;

    case "PostToolUse":
      s.waiting = false;
      if (isAgentTool(tool) && !ti.run_in_background) {
        // バックグラウンド実行はここでは終わらない（SubagentStop で完了扱い）
        const e = emp(ti.subagent_type || "general-purpose");
        e.active = Math.max(0, (e.active || 0) - 1);
        e.lastActive = now;
        if (!e.active) e.doing = "";
        finish(e, short(ti.description, 40) || "依頼対応");
        log(`📦 ${e.name} 完了「${short(ti.description, 30)}」`);
        s.now = `${e.name} の報告を確認中`;
      } else if (tool === "TaskCreate" && ti.subject) {
        const m = /#?(\d+)/.exec(ev.tool_response || "");
        notes.push({ id: m ? m[1] : null, t: ti.subject, state: "todo" });
        trimNotes();
      }
      break;

    case "SubagentStop": {
      const e = ev.agent_type && emps.get(ev.agent_type);
      if (e && e.bg > 0) {
        e.bg--; e.active = Math.max(0, (e.active || 0) - 1); e.lastActive = now;
        if (!e.active) e.doing = "";
        finish(e, e.task);
        log(`📦 ${e.name} 完了（バックグラウンド）「${short(e.task, 26)}」`);
      }
      break;
    }

    case "Notification": {
      const perm = ev.notification_type
        ? ev.notification_type === "permission_prompt"
        : /permission|許可/i.test(ev.message || "");
      if (perm) {
        s.waiting = true;
        s.now = "確認待ち：" + short(ev.message, 36);
        log(`🔔 Claude が社長の確認待ち（${s.project}）`);
      }
      break;
    }

    case "Stop":
      s.working = false; s.waiting = false;
      if (s.task) finish(main, s.task);
      log(`✅ Claude が作業完了${s.task ? "「" + short(s.task, 28) + "」" : ""}`);
      s.task = ""; s.now = "待機（指示待ち）";
      usageSoon();
      break;

    case "PreCompact":
      s.now = "記憶を整理中（compact）";
      break;

    case "SessionEnd":
      sessions.delete(sid);
      log(`🌙 Claude が退勤しました（${s.project}）`);
      break;
  }
  saveSoon();
  changed();
}

/* ───────── 状態の計算 ───────── */
function statusOf(e, now) {
  const last = Math.max(e.lastActive || 0, e.summonedAt || 0);
  if (e.id === "main") {
    let working = false, waiting = false;
    for (const s of sessions.values()) {
      if (s.waiting) waiting = true;
      else if (s.working && now - s.lastEvent < STUCK_MS) working = true;
    }
    if (waiting) return "wait"; // 確認待ちは一番目立たせる
    if (working) return "work";
    return (sessions.size || e.summonedAt) && now - last < IDLE_TO_REST ? "idle" : "rest";
  }
  if (e.active > 0 && now - (e.lastActive || 0) < SUB_STUCK_MS) return "work";
  return last && now - last < IDLE_TO_REST ? "idle" : "rest";
}
function mainNow(status, now) {
  if (!sessions.size) return "Claude Code はまだ起動していません";
  const list = [...sessions.values()].sort((a, b) => b.lastEvent - a.lastEvent);
  const tag = s => (sessions.size > 1 && s.project ? `[${s.project}] ` : "");
  const w = list.find(s => s.waiting);
  if (w) return tag(w) + w.now;
  const k = list.find(s => s.working && now - s.lastEvent < STUCK_MS);
  if (k) return tag(k) + k.now;
  return status === "rest" ? "休憩中（指示があれば即出動）" : "待機（指示待ち）";
}

function snapshot() {
  const now = Date.now();
  for (const [k, s] of sessions) if (now - s.lastEvent > SESSION_GONE_MS) sessions.delete(k);
  const d = today();
  const employees = [...emps.values()].map(e => {
    const status = statusOf(e, now);
    let nowText;
    if (e.id === "main") nowText = mainNow(status, now);
    else if (status === "work") nowText = (e.active > 1 ? `${e.task}（並列×${e.active}）` : e.task) + (e.doing ? ` ─ ${e.doing}` : "");
    else if (status === "idle") nowText = "待機（席で指示待ち）";
    else nowText = e.done ? "休憩中（ひと仕事終えた）" : "休憩中（出番待ち）";
    return {
      id: e.id, name: e.name, room: e.room, hair: e.hair, cloth: e.cloth, chat: !!e.chat, status,
      role: e.id === "main" && sessions.size > 1 ? `${e.role}・${sessions.size}窓` : e.role,
      now: nowText,
      done: e.done || "—",
      doneToday: e.doneDate === d ? e.doneCount : 0,
      next: e.next || "—",
    };
  });
  return { live: true, employees, notes, log: logs.slice(-15), usage, sessions: sessions.size };
}

/* ───────── SSE 配信 ───────── */
const clients = new Set();
let lastJson = JSON.stringify(snapshot());
let pushTimer = null;
function changed() {
  if (pushTimer) return;
  pushTimer = setTimeout(() => {
    pushTimer = null;
    const json = JSON.stringify(snapshot());
    if (json === lastJson) return;
    lastJson = json;
    for (const res of clients) res.write(`event: state\ndata: ${json}\n\n`);
  }, 150);
}
setInterval(changed, 20 * 1000);                                        // 待機→休憩などの時間経過による変化
setInterval(() => { for (const res of clients) res.write(": ping\n\n"); }, 25 * 1000).unref();

/* ───────── 使用量 ───────── */
let usageBusy = false, usageAt = 0;
async function refreshUsage() {
  if (usageBusy || process.env.VIRTUAL_OFFICE_NO_USAGE) return;
  usageBusy = true;
  try { usage = await collectUsage(); }
  catch (e) { usage = { ...(usage || {}), error: String(e.message || e) }; }
  finally { usageBusy = false; usageAt = Date.now(); changed(); }
}
function usageSoon() {
  if (Date.now() - usageAt > 60 * 1000) setTimeout(refreshUsage, 3000);
}

/* ───────── HTTP ───────── */
const ALLOWED_HOSTS = new Set([`127.0.0.1:${PORT}`, `localhost:${PORT}`, `[::1]:${PORT}`]);

function readBody(req, limit = 64 * 1024) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on("data", c => { size += c.length; if (size > limit) { reject(new Error("too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  // DNS リバインディング対策：localhost 以外の Host は拒否
  if (!ALLOWED_HOSTS.has(req.headers.host || "")) { res.writeHead(403).end("forbidden"); return; }
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/office.html")) {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
    res.end(readFileSync(path.join(DIR, "office.html")));
    return;
  }
  if (req.method === "GET" && url.pathname === "/usage.js") {
    res.writeHead(200, { "content-type": "text/javascript; charset=utf-8", "cache-control": "no-store" });
    res.end("window.USAGE = " + JSON.stringify(usage) + ";\n");
    return;
  }
  if (req.method === "GET" && url.pathname === "/events") {
    res.writeHead(200, { "content-type": "text/event-stream; charset=utf-8", "cache-control": "no-cache", connection: "keep-alive" });
    res.write("retry: 3000\n\n");
    res.write(`event: state\ndata: ${lastJson}\n\n`);
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/state") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(snapshot(), null, 1));
    return;
  }

  if (req.method === "POST") {
    // ブラウザからの不正な送信（CSRF）を防ぐため JSON 以外は受け付けない
    if (!(req.headers["content-type"] || "").startsWith("application/json")) { res.writeHead(415).end(); return; }
    let body;
    try { body = JSON.parse((await readBody(req)) || "{}"); }
    catch { res.writeHead(400).end(); return; }

    if (url.pathname === "/hook") {
      try { onHook(body); } catch (e) { console.error("hook error:", e); }
      res.writeHead(204).end();
      return;
    }
    if (url.pathname === "/api/summon") {
      // 休憩中の社員を席に呼び戻す（実際に仕事を振るのは Claude Code から）
      const now = Date.now();
      const targets = [...emps.values()].filter(e => (body.id ? e.id === body.id : e.room === body.room) && statusOf(e, now) === "rest");
      for (const e of targets) { e.summonedAt = now; log(`🫴 社長が ${e.name} を席に呼び戻しました`); }
      changed();
      res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ summoned: targets.map(e => e.name) }));
      return;
    }
    if (url.pathname === "/api/shutdown") {
      res.writeHead(204).end();
      console.log("停止リクエストを受けたので終了します");
      setTimeout(() => process.exit(0), 100);
      return;
    }
  }
  res.writeHead(404).end("not found");
});

server.on("error", e => {
  if (e.code === "EADDRINUSE") {
    console.log(`既に起動しています → http://127.0.0.1:${PORT}`);
    process.exit(0);
  }
  throw e;
});

loadState();
lastJson = JSON.stringify(snapshot());
server.listen(PORT, "127.0.0.1", () => {
  console.log(`バーチャルオフィス起動 → http://127.0.0.1:${PORT}`);
  refreshUsage();
  setInterval(refreshUsage, USAGE_INTERVAL);
});
