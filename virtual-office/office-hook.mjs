// Claude Code のフックから呼ばれ、イベントをバーチャルオフィスのサーバーへ送ります。
// install-hooks.mjs が ~/.claude/settings.json に登録します。
//
// 大事な約束:
//  - 何も標準出力しない（UserPromptSubmit などは出力が Claude の文脈に混ざるため）
//  - 常に exit 0（サーバーが落ちていても Claude Code の動作を一切止めない）
//  - ファイル内容などの大きなデータは送らない（必要な項目だけを抜き出して送る）

import http from "node:http";

const PORT = Number(process.env.VIRTUAL_OFFICE_PORT) || 4649;

function trunc(s, n) {
  if (typeof s !== "string") return undefined;
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function slim(ev) {
  const ti = ev.tool_input || {};
  const out = {
    hook_event_name: ev.hook_event_name,
    session_id: ev.session_id,
    cwd: ev.cwd,
    tool_name: ev.tool_name,
    prompt: trunc(ev.prompt, 200),
    message: trunc(ev.message, 200),
    notification_type: ev.notification_type,
    agent_type: ev.agent_type,
    agent_id: ev.agent_id,
    source: ev.source,
    reason: ev.reason,
    model: typeof ev.model === "string" ? ev.model : ev.model && ev.model.display_name,
  };
  if (ev.tool_input) {
    out.tool_input = {
      file_path: ti.file_path || ti.notebook_path,
      command: trunc(ti.command, 120),
      pattern: trunc(ti.pattern, 80),
      description: trunc(ti.description, 120),
      subagent_type: ti.subagent_type,
      run_in_background: ti.run_in_background,
      url: trunc(ti.url, 200),
      query: trunc(ti.query, 120),
      skill: ti.skill,
      subject: trunc(ti.subject || ti.title, 120),
      taskId: ti.taskId ?? ti.task_id ?? ti.id,
      status: ti.status,
      todos: Array.isArray(ti.todos)
        ? ti.todos.slice(0, 20).map(t => ({ content: trunc(t.content, 120), status: t.status, activeForm: trunc(t.activeForm, 120) }))
        : undefined,
    };
  }
  // タスク作成の結果からIDだけ拾う（案件ボード用）
  if (ev.tool_name === "TaskCreate" && ev.tool_response != null) {
    out.tool_response = trunc(typeof ev.tool_response === "string" ? ev.tool_response : JSON.stringify(ev.tool_response), 300);
  }
  return out;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", c => { raw += c; });
process.stdin.on("end", () => {
  let body;
  try { body = JSON.stringify(slim(JSON.parse(raw))); } catch { process.exit(0); }
  const req = http.request(
    { host: "127.0.0.1", port: PORT, path: "/hook", method: "POST", timeout: 400,
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) } },
    res => { res.resume(); res.on("end", () => process.exit(0)); }
  );
  req.on("error", () => process.exit(0));
  req.on("timeout", () => { req.destroy(); process.exit(0); });
  req.end(body);
});
// 念のための保険（何があっても1秒で終了）
setTimeout(() => process.exit(0), 1000).unref();
