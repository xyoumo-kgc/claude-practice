/* 英語学習ノート アプリ本体（依存ライブラリなし / localStorage 保存） */
"use strict";

/* ===================== 保存 ===================== */
const STORE_KEY = "english-learning-app:v1";
const SRS_INTERVALS = { 1: 1, 2: 3, 3: 7, 4: 14, 5: 30 };
const MODELS = [
  ["claude-opus-5-5", "Claude Opus 5.5（標準）"],
  ["claude-sonnet-5-5", "Claude Sonnet 5.5（速い・安い）"],
  ["claude-haiku-5-5", "Claude Haiku 5.5（最速・最安）"],
];
const GRAMMAR_CAT = { be: "語順", present: "三単現", progressive: "時制", past: "時制", future: "時制", question: "語順", negative: "語順",
  article: "冠詞", countable: "可算不可算", preposition: "前置詞", modal: "その他", perfect: "時制", comparative: "その他", relative: "語順", passive: "時制", conditional: "時制" };

function defaultState() {
  return {
    status: { phase: 1, startDate: null, minutesPerDay: 20, goal: "" },
    vocab: [], mistakes: [], log: [], doneLessons: {}, doneGrammar: {}, checks: {}, customLessons: [],
    settings: { apiKey: "", model: "claude-opus-5-5" }, nextId: 1,
  };
}
let S = defaultState();
function load() {
  try { const raw = localStorage.getItem(STORE_KEY); if (raw) S = Object.assign(defaultState(), JSON.parse(raw)); } catch (e) { /* 読めなければ初期状態 */ }
}
function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (e) { toast("保存できませんでした（ブラウザの保存領域が使えません）"); } }

/* ===================== ユーティリティ ===================== */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function addDays(iso, n) { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function shuffle(a) { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 2600); }
function speak(text) {
  if (!("speechSynthesis" in window)) { toast("この端末では音声読み上げが使えません"); return; }
  const u = new SpeechSynthesisUtterance(text); u.lang = "en-US"; u.rate = 0.9;
  const v = speechSynthesis.getVoices().find((x) => x.lang === "en-US") || speechSynthesis.getVoices().find((x) => x.lang.startsWith("en"));
  if (v) u.voice = v; speechSynthesis.cancel(); speechSynthesis.speak(u);
}
const spk = (text) => `<button class="spk" data-action="speak" data-text="${esc(text)}" title="読み上げ" aria-label="読み上げ">🔊</button>`;
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("コピーしました"); }
  catch (e) { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); toast("コピーしました"); } catch (_) { toast("コピーできませんでした"); } ta.remove(); }
}
const CONTRACTIONS = [[/\bi am\b/g, "i'm"], [/\byou are\b/g, "you're"], [/\bit is\b/g, "it's"], [/\bthat is\b/g, "that's"], [/\bdo not\b/g, "don't"], [/\bdoes not\b/g, "doesn't"], [/\bdid not\b/g, "didn't"],
  [/\bi have\b/g, "i've"], [/\bhave not\b/g, "haven't"], [/\bi would\b/g, "i'd"], [/\bi will\b/g, "i'll"], [/\bis not\b/g, "isn't"], [/\bwhere is\b/g, "where's"], [/\bcan not\b/g, "can't"], [/\bcannot\b/g, "can't"]];
function norm(s) {
  s = String(s ?? "").toLowerCase().replace(/[’‘]/g, "'").replace(/[.,!?;:、。！？"]/g, " ").replace(/\s+/g, " ").trim();
  for (const [re, rep] of CONTRACTIONS) s = s.replace(re, rep);
  return s;
}
const matches = (input, answers) => { const n = norm(input); return answers.some((a) => norm(a) === n); };

/* ===================== 学習ログ操作 ===================== */
function addVocab(kind, en, ja, ex, source, cat) {
  const dup = S.vocab.find((v) => norm(v.en) === norm(en));
  if (dup) return dup;
  const item = { id: S.nextId++, kind, en, ja, ex: ex || "", learned: today(), box: 1, next: addDays(today(), 1), source, cat: cat || null };
  S.vocab.push(item); return item;
}
function gradeVocab(id, ok) {
  const v = S.vocab.find((x) => x.id === id); if (!v) return;
  v.box = ok ? Math.min(v.box + 1, 5) : 1; v.next = addDays(today(), SRS_INTERVALS[v.box]);
}
function addMistake(wrong, right, cat, source) { S.mistakes.push({ date: today(), wrong, right, cat: cat || "その他", source }); }
function addLog(kind, note, minutes) { S.log.push({ date: today(), kind, note, minutes: minutes || 0 }); }
function dueItems() { const t = today(); return S.vocab.filter((v) => v.next <= t).sort((a, b) => a.box - b.box || a.next.localeCompare(b.next)); }
function streak() {
  const days = [...new Set(S.log.map((l) => l.date))].sort().reverse(); if (!days.length) return 0;
  let cur = days[0] === today() ? today() : addDays(today(), -1); if (days[0] !== cur) return 0;
  let n = 0; for (const d of days) { if (d !== cur) break; n++; cur = addDays(cur, -1); } return n;
}
function mistakeStats() { const c = {}; for (const m of S.mistakes) c[m.cat] = (c[m.cat] || 0) + 1; return Object.entries(c).sort((a, b) => b[1] - a[1]); }
const allLessons = () => LESSONS.concat(S.customLessons);
const phaseOf = (p) => PLAN.find((x) => x.phase === p);

/* ===================== Claude API ===================== */
async function callClaude(system, messages, opts = {}) {
  const key = S.settings.apiKey.trim();
  if (!key) throw new Error("NO_KEY");
  const model = S.settings.model;
  const body = { model, max_tokens: opts.maxTokens || 4096, system, messages, output_config: { effort: "low" } };
  const headers = { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2026-10-21", "anthropic-dangerous-direct-browser-access": "true" };
  if (model.startsWith("claude-opus") || model.startsWith("claude-sonnet")) { body.fallbacks = "default"; headers["anthropic-beta"] = "server-side-fallback-2026-07-01"; }
  const res = await fetch("https://api.anthropic.com/v1/messages", { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok) { const t = await res.text(); throw new Error(`API エラー ${res.status}: ${t.slice(0, 300)}`); }
  const data = await res.json();
  if (data.stop_reason === "refusal") throw new Error("リクエストが安全上の理由で拒否されました。内容を変えて再試行してください。");
  return data.content.filter((b) => b.type === "text").map((b) => b.text).join("");
}
function parseJSON(text) {
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a < 0 || b < 0) throw new Error("JSON が見つかりません");
  return JSON.parse(text.slice(a, b + 1));
}
function learnerContext() {
  const ph = phaseOf(S.status.phase);
  const recent = S.vocab.slice(-30).map((v) => v.en).join(", ");
  const weak = mistakeStats().slice(0, 3).map(([k, n]) => `${k}(${n})`).join(", ");
  return `学習者: 日本語話者の大人。現在フェーズ ${S.status.phase}「${ph.title}」（${ph.level}）。目標: ${S.status.goal || "未設定"}。\n最近学んだ語彙: ${recent || "なし"}。\n間違えやすい分類: ${weak || "まだデータなし"}。`;
}
function apiErrorHtml(e) {
  if (e.message === "NO_KEY") return `<div class="warn">API キーが未設定です。<a href="#settings">設定</a>で入力するか、下の「プロンプトをコピー」で Claude.ai / ChatGPT に貼り付けて使ってください。</div>`;
  return `<div class="warn">${esc(e.message)}</div>`;
}

/* ===================== 画面 ===================== */
const UI = { lesson: null, review: null, chat: null, roleplay: null, correct: null, grammar: null };
const ROUTES = { home: "ホーム", plan: "計画", lesson: "レッスン", grammar: "文法", review: "復習", correct: "添削", chat: "会話", roleplay: "ロールプレイ", progress: "記録", settings: "設定" };

function render() {
  const hash = (location.hash || "#home").slice(1).split("/");
  const route = ROUTES[hash[0]] ? hash[0] : "home";
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + route));
  const view = $("#view");
  const fn = { home: vHome, plan: vPlan, lesson: vLesson, grammar: vGrammar, review: vReview, correct: vCorrect, chat: vChat, roleplay: vRoleplay, progress: vProgress, settings: vSettings }[route];
  view.innerHTML = fn(hash.slice(1));
  view.scrollTop = 0; window.scrollTo(0, 0);
}

/* ---------- ホーム ---------- */
function vHome() {
  const ph = phaseOf(S.status.phase), due = dueItems().length, st = streak();
  const dow = new Date().getDay();
  const plan = dow === 0 ? "復習テストまとめ（10分）→ 週の振り返り" : dow === 6 ? "ロールプレイ（20分）" : [2, 4].includes(dow) ? "復習テスト（5分）→ 会話練習（15分）" : "復習テスト（5分）→ 今日のレッスン（15分）";
  const lastGood = S.vocab.filter((v) => v.box >= 5).length;
  return `
  <section class="hero">
    <div><div class="eyebrow">フェーズ ${ph.phase} · ${esc(ph.level)}</div><h1>${esc(ph.title)}</h1><p>${esc(ph.goal)}</p></div>
    <div class="stats">
      <div class="stat"><b>${st}</b><span>連続日数</span></div>
      <div class="stat ${due ? "hot" : ""}"><b>${due}</b><span>復習待ち</span></div>
      <div class="stat"><b>${S.vocab.length}</b><span>学んだ項目</span></div>
      <div class="stat"><b>${lastGood}</b><span>定着（Box5）</span></div>
    </div>
  </section>
  <section class="card">
    <h2>今日の予定 <small>${["日", "月", "火", "水", "木", "金", "土"][dow]}曜日</small></h2>
    <p class="big">${esc(plan)}</p>
    <div class="actions">
      <a class="btn primary" href="#review">復習テスト${due ? ` (${due})` : ""}</a>
      <a class="btn" href="#lesson">今日のレッスン</a>
      <a class="btn" href="#chat">会話練習</a>
      <a class="btn" href="#roleplay">ロールプレイ</a>
    </div>
  </section>
  <section class="grid2">
    <div class="card"><h2>最近学んだこと</h2>${S.vocab.length ? `<ul class="plain">${S.vocab.slice(-6).reverse().map((v) => `<li><b>${esc(v.en)}</b> — ${esc(v.ja.length > 50 ? v.ja.slice(0, 50) + "…" : v.ja)} <span class="pill">Box${v.box}</span></li>`).join("")}</ul>` : `<p class="dim">まだありません。<a href="#lesson">レッスン</a>から始めましょう。</p>`}</div>
    <div class="card"><h2>間違えやすい箇所</h2>${S.mistakes.length ? bars(mistakeStats().slice(0, 5)) : `<p class="dim">まだデータがありません。レッスンや添削の結果がここに溜まります。</p>`}</div>
  </section>
  ${S.status.startDate ? "" : `<section class="card tip"><b>はじめての方へ</b> <a href="#settings">設定</a>で現在のフェーズと1日の時間を決め、<a href="#plan">計画</a>で全体像を確認してから、<a href="#lesson">レッスン</a>を1本やってみてください。</section>`}`;
}
function bars(stats) {
  const max = Math.max(...stats.map((s) => s[1]), 1);
  return `<div class="bars">${stats.map(([k, n]) => `<div class="bar"><span class="lbl">${esc(k)}</span><span class="trk"><span class="fil" style="width:${(n / max) * 100}%"></span></span><span class="num">${n}</span></div>`).join("")}</div>`;
}

/* ---------- 計画 ---------- */
function vPlan() {
  return `<h1>英語マスター学習計画（5フェーズ）</h1>
  <p class="dim">1日15〜25分を毎日続ける前提。各フェーズの週数は<b>目安（推測）</b>で、進級は「卒業チェック」を満たしたかで判断する。</p>
  <div class="phases">${PLAN.map((p) => {
    const cur = p.phase === S.status.phase, checks = S.checks[p.phase] || {};
    const done = p.checks.filter((_, i) => checks[i]).length;
    return `<details class="phase ${cur ? "cur" : ""}" ${cur ? "open" : ""}>
      <summary><span class="num">${p.phase}</span><span class="t"><b>${esc(p.title)}</b><small>${esc(p.level)} · ${esc(p.weeks)}</small></span><span class="prog">${done}/${p.checks.length}</span></summary>
      <p class="goal">${esc(p.goal)}</p>
      <table class="tbl"><tbody>${p.learn.map(([a, b]) => `<tr><th>${esc(a)}</th><td>${esc(b)}</td></tr>`).join("")}</tbody></table>
      <h4>毎日のやり方</h4><ul>${p.routine.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      <h4>卒業チェック</h4>
      <ul class="checks">${p.checks.map((c, i) => `<li><label><input type="checkbox" data-action="check" data-phase="${p.phase}" data-i="${i}" ${checks[i] ? "checked" : ""}> ${esc(c)}</label></li>`).join("")}</ul>
      ${cur ? "" : `<button class="btn sm" data-action="set-phase" data-phase="${p.phase}">このフェーズを現在地にする</button>`}
    </details>`; }).join("")}</div>
  <section class="card"><h2>1週間の基本ルーティン</h2><table class="tbl">${WEEKLY_ROUTINE.map(([d, c]) => `<tr><th>${esc(d)}</th><td>${esc(c)}</td></tr>`).join("")}</table></section>
  <section class="card"><h2>つまずいたときの対処</h2><table class="tbl">${TROUBLESHOOT.map(([d, c]) => `<tr><th>${esc(d)}</th><td>${esc(c)}</td></tr>`).join("")}</table></section>`;
}

/* ---------- レッスン ---------- */
function vLesson(args) {
  if (args[0]) { const L = allLessons().find((l) => l.id === args[0]); if (L) return lessonRunner(L); }
  const byPhase = {};
  for (const L of allLessons()) (byPhase[L.phase] = byPhase[L.phase] || []).push(L);
  return `<h1>毎日のレッスン</h1>
  <p class="dim">1本 15〜20分。語彙 → 文の形成 → 発音 → 演習 → 記録の順。終えると語彙が復習リストに入る。</p>
  <section class="card ai">
    <h2>AI でレッスンを生成する <small>API キー設定時</small></h2>
    <div class="row"><input id="gen-theme" placeholder="テーマ（例: スーパーで買い物、週末の予定、体調を伝える）"><button class="btn primary" data-action="gen-lesson">生成</button></div>
    <div id="gen-out"></div>
  </section>
  ${Object.keys(byPhase).sort().map((p) => `<h3>フェーズ ${p} · ${esc(phaseOf(+p).title)}</h3><div class="cards">${byPhase[p].map((L) => `
    <a class="lesson ${S.doneLessons[L.id] ? "done" : ""}" href="#lesson/${L.id}">
      <b>${esc(L.title)}</b><small>${L.vocab.length} 語 · ${L.minutes} 分${L.custom ? " · AI生成" : ""}</small>
      ${S.doneLessons[L.id] ? `<span class="pill ok">完了 ${esc(S.doneLessons[L.id])}</span>` : ""}
    </a>`).join("")}</div>`).join("")}`;
}
function lessonRunner(L) {
  UI.lesson = { id: L.id, graded: null };
  return `<a class="back" href="#lesson">← レッスン一覧</a>
  <h1>${esc(L.title)} <small>フェーズ ${L.phase} · 約 ${L.minutes} 分</small></h1>
  <section class="card"><h2>1. 今日の語彙 <small>4分 · すべて3回音読</small></h2>
    <table class="tbl vocab"><thead><tr><th>英語</th><th>発音</th><th>意味</th><th>例文</th></tr></thead><tbody>
    ${L.vocab.map(([en, ipa, ja, ex]) => `<tr><td><b>${esc(en)}</b> ${spk(en)}</td><td class="ipa">${esc(ipa)}</td><td>${esc(ja)}</td><td>${esc(ex)} ${spk(ex)}</td></tr>`).join("")}</tbody></table></section>
  <section class="card"><h2>2. 文の形成 <small>4分</small></h2>
    <p class="big">今日の型: <b>${esc(L.pattern.name)}</b></p>
    <ul>${L.pattern.lines.map((l) => `<li>${esc(l)} ${spk(l.split("→").pop().trim())}</li>`).join("")}</ul>
    <p class="note">${esc(L.pattern.note)}</p>
    <p>自分の情報で3文作る（声に出してから書く）:</p>
    ${L.pattern.prompts.map((p, i) => `<div class="row"><label class="dim">${esc(p)}</label><input class="own" data-i="${i}" placeholder="英語で"></div>`).join("")}
    <button class="btn sm" data-action="own-to-correct">この3文を添削に送る</button></section>
  <section class="card"><h2>3. 発音ガイド <small>3分</small></h2>
    <p class="big">今日の音: <b>${esc(L.pron.sound)}</b></p><p>${esc(L.pron.how)}</p>
    <p>ミニマルペア: ${L.pron.pairs.map((p) => `<span class="pair">${esc(p)} ${spk(p.replace("/", ","))}</span>`).join(" ")}</p>
    <p>早口言葉（3回）: <i>${esc(L.pron.tongue)}</i> ${spk(L.pron.tongue)}</p></section>
  <section class="card"><h2>4. 実践演習 <small>5分</small></h2>
    <form id="ex-form" onsubmit="return false">
    ${L.exercises.map((ex, i) => {
      if (ex.type === "fill") return `<div class="ex" data-i="${i}"><span class="qn">${i + 1}</span><div><p>${esc(ex.q)}</p><div class="choices">${ex.choices.map((c) => `<label><input type="radio" name="ex${i}" value="${esc(c)}"> ${esc(c)}</label>`).join("")}</div><div class="fb"></div></div></div>`;
      if (ex.type === "order") return `<div class="ex" data-i="${i}"><span class="qn">${i + 1}</span><div><p>並べ替え: <span class="words">${shuffle(ex.words).map((w) => `<code>${esc(w)}</code>`).join(" ")}</span></p><input name="ex${i}" placeholder="文を入力" autocomplete="off"><div class="fb"></div></div></div>`;
      return `<div class="ex" data-i="${i}"><span class="qn">${i + 1}</span><div><p>日本語 → 英語: <b>${esc(ex.ja)}</b></p><input name="ex${i}" placeholder="英語で" autocomplete="off"><div class="fb"></div></div></div>`;
    }).join("")}
    </form>
    <div class="actions"><button class="btn primary" data-action="grade-lesson">採点する</button></div>
    <div id="lesson-result"></div></section>
  <section class="card"><h2>5. 記録</h2><p class="dim">採点後、「完了」を押すと語彙 ${L.vocab.length} 件と今日の型が復習リストに登録され、間違いがログに残る。</p>
    <button class="btn primary" id="finish-btn" data-action="finish-lesson" disabled>完了して登録する</button></section>`;
}
function gradeLesson() {
  const L = allLessons().find((l) => l.id === UI.lesson.id); const form = $("#ex-form"); let score = 0; const wrong = [];
  L.exercises.forEach((ex, i) => {
    const el = form.querySelector(`.ex[data-i="${i}"]`), fb = el.querySelector(".fb");
    let val = ex.type === "fill" ? (form.querySelector(`input[name="ex${i}"]:checked`) || {}).value || "" : form.querySelector(`input[name="ex${i}"]`).value;
    const ok = matches(val, ex.answers || [ex.answer]);
    el.classList.toggle("ok", ok); el.classList.toggle("ng", !ok);
    const ans = (ex.answers || [ex.answer])[0];
    if (ok) { score++; fb.innerHTML = `<span class="good">○</span>`; }
    else {
      fb.innerHTML = `<span class="bad">×</span> 正解: <b>${esc(ans)}</b> ${ex.type !== "fill" ? `<button class="btn xs" data-action="accept" data-i="${i}">自分の答えも正解とみなす</button>` : ""}`;
      wrong.push({ i, wrong: val || "（無回答）", right: ans, cat: ex.type === "fill" ? "語彙の選択" : ex.type === "order" ? "語順" : "その他" });
    }
  });
  UI.lesson.graded = { score, total: L.exercises.length, wrong };
  $("#lesson-result").innerHTML = `<p class="big">${score} / ${L.exercises.length} 正解</p><h4>よくある間違い</h4><ul>${L.common.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
  $("#finish-btn").disabled = false;
}
function finishLesson() {
  const L = allLessons().find((l) => l.id === UI.lesson.id); const g = UI.lesson.graded; if (!g) return;
  for (const [en, , ja, ex] of L.vocab) addVocab("語彙", en, ja, ex, "lesson");
  addVocab("文法", L.pattern.name, L.pattern.note, L.pattern.lines[0].split("→").pop().trim(), "lesson", "語順");
  for (const w of g.wrong) addMistake(w.wrong, w.right, w.cat, "lesson");
  addLog("lesson", `${L.title}（${g.score}/${g.total}）`, L.minutes);
  S.doneLessons[L.id] = today(); if (!S.status.startDate) S.status.startDate = today();
  save(); toast(`登録しました。明日の復習テストに ${L.vocab.length + 1} 件入ります`); location.hash = "#lesson";
}
async function genLesson() {
  const theme = $("#gen-theme").value.trim(); const out = $("#gen-out");
  if (!theme) { toast("テーマを入力してください"); return; }
  out.innerHTML = `<p class="dim">生成中…（20〜40秒）</p>`;
  const sys = `あなたは日本語話者向けの英語教師です。${learnerContext()}\n次の JSON だけを出力してください（説明文や \`\`\` は不要）。合計15〜20分で終わる分量にし、例文はテーマの会話で本当に使う文にします。発音の説明はカタカナを使わず、発音記号と口の形で説明します。
{"title":"レッスン名(日本語)","minutes":18,"vocab":[["英語","/発音記号/","意味(日本語)","例文"] ×6〜8],
"pattern":{"name":"今日の型(日本語+英語)","lines":["例文1","例文2","例文3"],"note":"ポイント(日本語)","prompts":["学習者が作る文の穴あき1","2","3"]},
"pron":{"sound":"今日の音","how":"口の形・日本語との違い","pairs":["a / b","c / d","e / f"],"tongue":"早口言葉"},
"exercises":[{"type":"fill","q":"______ を含む文","answers":["正解"],"choices":["正解","誤り1","誤り2"]} ×5, {"type":"order","words":["単語",...],"answer":"正しい文"} ×3, {"type":"ja2en","ja":"日本語","answers":["英訳1","別解"]} ×3],
"common":["よくある間違い1","2"]}`;
  try {
    const text = await callClaude(sys, [{ role: "user", content: `テーマ: ${theme}` }], { maxTokens: 6000 });
    const j = parseJSON(text);
    const L = Object.assign({ phase: S.status.phase, custom: true, id: "ai-" + Date.now() }, j);
    if (!Array.isArray(L.vocab) || !L.exercises || !L.pattern || !L.pron) throw new Error("生成結果の形式が不正でした。もう一度お試しください。");
    S.customLessons.push(L); save(); location.hash = "#lesson/" + L.id;
  } catch (e) { out.innerHTML = apiErrorHtml(e) + `<button class="btn sm" data-action="copy-prompt" data-kind="lesson" data-theme="${esc(theme)}">プロンプトをコピー（Claude.ai 等で使う）</button>`; }
}

/* ---------- 文法 ---------- */
function vGrammar(args) {
  if (args[0]) { const G = GRAMMAR.find((g) => g.id === args[0]); if (G) return grammarDetail(G); }
  return `<h1>文法を会話でつかむ</h1><p class="dim">理屈より先に「こう言えばこう伝わる」。一言ルール → 会話例 → つまずく点。1日1項目、会話例を3回音読してから自分の例文を3つ作る。</p>
  <div class="cards">${GRAMMAR.map((g, i) => `<a class="lesson ${S.doneGrammar[g.id] ? "done" : ""}" href="#grammar/${g.id}"><b>${i + 1}. ${esc(g.title)}</b><small>フェーズ ${g.phase} から · 分類: ${esc(GRAMMAR_CAT[g.id])}</small>${S.doneGrammar[g.id] ? `<span class="pill ok">学習済み</span>` : ""}</a>`).join("")}</div>
  <section class="card ai"><h2>他の文法を質問する <small>API キー設定時</small></h2>
    <div class="row"><input id="gq" placeholder="例: some と any の違い / 第4文型 / used to"><button class="btn primary" data-action="ask-grammar">会話例で説明</button></div><div id="gq-out"></div></section>`;
}
function grammarDetail(G) {
  return `<a class="back" href="#grammar">← 文法一覧</a><h1>${esc(G.title)}</h1>
  <section class="card"><h2>一言ルール</h2><p class="big">${esc(G.rule)}</p></section>
  <section class="card"><h2>会話例 <small>3回音読</small></h2><div class="dialog">${G.dialog.map((l) => `<p>${esc(l)} ${spk(l.replace(/^[AB]:\s*/, ""))}</p>`).join("")}</div></section>
  <section class="card"><h2>日本語話者がつまずく点</h2><table class="tbl">${G.pitfalls.map((p) => `<tr><td class="bad">× ${esc(p.bad)}</td><td class="good">○ ${esc(p.good)}</td><td>${esc(p.note)}</td></tr>`).join("")}</table></section>
  <section class="card"><h2>自分で3文</h2>${[1, 2, 3].map((i) => `<input class="own" data-i="${i}" placeholder="このルールを使った文 ${i}">`).join("")}
    <div class="actions"><button class="btn" data-action="own-to-correct">添削に送る</button><button class="btn primary" data-action="learn-grammar" data-id="${G.id}">学習済みにして復習リストへ</button></div></section>`;
}
async function askGrammar() {
  const q = $("#gq").value.trim(), out = $("#gq-out"); if (!q) return;
  out.innerHTML = `<p class="dim">考え中…</p>`;
  const sys = `あなたは日本語話者向けの英語教師です。${learnerContext()}\n質問された文法を次の固定形式・日本語で説明します（例文は英語）。抽象的な用語は最小限。\n## 一言ルール\n## 会話例（A/B 4〜6行、対象の文法が3回以上登場）\n## どう機能しているか（会話例を引用して2〜3点）\n## 日本語話者がつまずく点（× → ○ を1〜3組）\n## 自分で3文（場面を指定した空欄）`;
  try { const t = await callClaude(sys, [{ role: "user", content: q }]); out.innerHTML = `<div class="md">${md(t)}</div>`; }
  catch (e) { out.innerHTML = apiErrorHtml(e) + `<button class="btn sm" data-action="copy-prompt" data-kind="grammar" data-theme="${esc(q)}">プロンプトをコピー</button>`; }
}

/* ---------- 復習（間隔反復） ---------- */
function vReview() {
  if (UI.review && UI.review.active) return reviewQuestion();
  const due = dueItems(), total = S.vocab.length;
  if (!total) return `<h1>復習テスト</h1><p class="dim">まだ学んだ項目がありません。<a href="#lesson">レッスン</a>か<a href="#grammar">文法</a>から始めてください。</p>`;
  const boxes = [1, 2, 3, 4, 5].map((b) => S.vocab.filter((v) => v.box === b).length);
  return `<h1>復習テスト <small>間隔反復</small></h1>
  <section class="card"><p class="big">復習期限の項目: <b>${due.length}</b> 件 <span class="dim">/ 全 ${total} 件</span></p>
    <div class="boxes">${boxes.map((n, i) => `<div class="box"><b>${n}</b><span>Box${i + 1}<br><small>${SRS_INTERVALS[i + 1]}日</small></span></div>`).join("")}</div>
    <p class="dim">古い項目（期限）6〜7割、最近の項目3〜4割を混ぜて10〜12問。穴埋め・日→英・英→日。正解で Box が1つ上がり、不正解で Box1 に戻る。</p>
    <div class="actions"><button class="btn primary" data-action="start-review">${due.length ? "テストを始める" : "期限の項目はないが練習する"}</button></div></section>
  ${S.mistakes.length ? `<section class="card"><h2>最も間違えやすい箇所</h2>${bars(mistakeStats().slice(0, 5))}<p class="dim">上位の分類を <a href="#grammar">文法</a> で復習し、<a href="#correct">添削</a>で「${esc(mistakeStats()[0][0])}だけ見て」と指定して集中練習するのが効く。</p></section>` : ""}`;
}
function startReview() {
  const due = dueItems(); const dueIds = new Set(due.map((v) => v.id));
  const recent = S.vocab.filter((v) => !dueIds.has(v.id)).sort((a, b) => b.learned.localeCompare(a.learned));
  const weakCats = new Set(mistakeStats().slice(0, 2).map((s) => s[0]));
  let pick = due.sort((a, b) => (weakCats.has(a.cat) ? -1 : 0) - (weakCats.has(b.cat) ? -1 : 0) || a.box - b.box).slice(0, 8);
  pick = pick.concat(recent.slice(0, Math.max(4, 12 - pick.length)));
  if (pick.length < 10) pick = pick.concat(shuffle(S.vocab.filter((v) => !pick.includes(v))).slice(0, 10 - pick.length));
  pick = shuffle(pick).slice(0, 12);
  const qs = pick.map((v, i) => {
    const types = ["fill", "ja2en", "en2ja"]; let type = types[i % 3];
    const canBlank = v.ex && norm(v.ex).includes(norm(v.en)) && v.kind !== "文法";
    if (type === "fill" && !canBlank) type = "ja2en";
    if (v.kind === "文法") type = i % 2 ? "en2ja" : "ja2en";
    return { v, type };
  });
  UI.review = { active: true, qs, idx: 0, results: [] }; render();
}
function reviewQuestion() {
  const R = UI.review, q = R.qs[R.idx], v = q.v;
  let body;
  if (q.type === "fill") {
    const re = new RegExp(v.en.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"); const blank = v.ex.replace(re, "______");
    body = `<p class="eyebrow">穴埋め（ヒント: ${esc(v.ja)}）</p><p class="big">${esc(blank)}</p><input id="rv-in" placeholder="空欄に入る語" autocomplete="off" autofocus>`;
  } else if (q.type === "ja2en") {
    body = `<p class="eyebrow">日本語 → 英語${v.kind === "文法" ? "（この文法を使って例文を1つ）" : ""}</p><p class="big">${esc(v.kind === "文法" ? v.en + " — " + v.ja : v.ja)}</p>${v.kind === "文法" ? `<p class="dim">お手本: ${esc(v.ex)}</p>` : ""}<input id="rv-in" placeholder="英語で" autocomplete="off" autofocus>`;
  } else {
    body = `<p class="eyebrow">英語 → 日本語${v.kind === "文法" ? "（ルールを自分の言葉で）" : ""}</p><p class="big">${esc(v.kind === "文法" ? v.ex : v.ex || v.en)} ${spk(v.ex || v.en)}</p><input id="rv-in" placeholder="日本語で意味を" autocomplete="off" autofocus>`;
  }
  return `<h1>復習テスト <small>${R.idx + 1} / ${R.qs.length}</small></h1>
  <div class="progress"><span style="width:${(R.idx / R.qs.length) * 100}%"></span></div>
  <section class="card quiz" data-type="${q.type}">${body}
    <div class="actions"><button class="btn primary" data-action="rv-answer">答える</button><button class="btn" data-action="rv-quit">中断して採点</button></div>
    <div id="rv-fb"></div></section>`;
}
function reviewAnswer() {
  const R = UI.review, q = R.qs[R.idx], v = q.v, val = $("#rv-in").value; const fb = $("#rv-fb");
  if (q.type === "en2ja" || (q.type === "ja2en" && v.kind === "文法")) {
    const answer = q.type === "en2ja" ? (v.kind === "文法" ? v.ja : v.ja) : v.ex;
    fb.innerHTML = `<p>あなたの答え: <b>${esc(val || "（無回答）")}</b></p><p>正解: <b>${esc(answer)}</b></p><p>自己採点:</p><div class="actions"><button class="btn primary" data-action="rv-self" data-ok="1">○ 合っていた</button><button class="btn" data-action="rv-self" data-ok="0">× 違った</button></div>`;
    $("[data-action=rv-answer]").disabled = true; return;
  }
  const ok = q.type === "fill" ? norm(val) === norm(v.en) : matches(val, [v.ex, v.en]);
  recordReview(ok, val);
}
function recordReview(ok, val) {
  const R = UI.review, q = R.qs[R.idx], v = q.v;
  R.results.push({ id: v.id, ok, val }); gradeVocab(v.id, ok);
  if (!ok) addMistake(val || "（無回答）", q.type === "en2ja" ? v.ja : (v.ex || v.en), v.cat || (v.kind === "文法" ? "その他" : "語彙の選択"), "review");
  const fb = $("#rv-fb");
  fb.innerHTML = `<p class="${ok ? "good" : "bad"} big">${ok ? "○ 正解" : "× 不正解"}</p><p>${esc(v.en)} — ${esc(v.ja)}<br><i>${esc(v.ex)}</i> ${spk(v.ex || v.en)}</p><p class="dim">Box ${v.box} → 次回 ${v.next}</p><div class="actions"><button class="btn primary" data-action="rv-next">${R.idx + 1 < R.qs.length ? "次へ" : "結果を見る"}</button></div>`;
  const b = $("[data-action=rv-answer]"); if (b) b.disabled = true;
  save();
}
function reviewNext() { const R = UI.review; R.idx++; if (R.idx >= R.qs.length) return reviewFinish(); render(); setTimeout(() => { const i = $("#rv-in"); if (i) i.focus(); }, 0); }
function reviewFinish() {
  const R = UI.review; R.active = false;
  const ok = R.results.filter((r) => r.ok).length, n = R.results.length;
  const todayCats = {}; for (const r of R.results) if (!r.ok) { const v = S.vocab.find((x) => x.id === r.id); const c = v.cat || (v.kind === "文法" ? "その他" : "語彙の選択"); todayCats[c] = (todayCats[c] || 0) + 1; }
  const top = mistakeStats().slice(0, 2);
  const settled = R.results.filter((r) => r.ok && S.vocab.find((x) => x.id === r.id).box === 5).map((r) => S.vocab.find((x) => x.id === r.id).en);
  if (n) addLog("review", `復習テスト ${ok}/${n}`, 7);
  save();
  $("#view").innerHTML = `<h1>復習テスト 結果</h1>
  <section class="card"><p class="big">${ok} / ${n} 正解</p>
    <ul class="plain">${R.results.map((r) => { const v = S.vocab.find((x) => x.id === r.id); return `<li>${r.ok ? '<span class="good">○</span>' : '<span class="bad">×</span>'} <b>${esc(v.en)}</b> — ${esc(v.ja)} <span class="pill">Box${v.box} · 次回 ${v.next}</span></li>`; }).join("")}</ul></section>
  <section class="card"><h2>最も間違えやすい箇所</h2>
    ${Object.keys(todayCats).length ? `<p>今日の×: ${Object.entries(todayCats).map(([k, v]) => `${esc(k)} ${v}`).join("、")}</p>` : `<p class="good">今日は全問正解です。</p>`}
    ${top.length ? `<p>累計で多いのは <b>${top.map(([k, v]) => `${esc(k)}（${v}）`).join("、")}</b>。次に集中する練習: <a href="#grammar">文法</a>で該当項目を音読 → <a href="#correct">添削</a>で「${esc(top[0][0])}だけ見て」と指定。</p>` : ""}
    ${settled.length ? `<p class="good">定着（Box5）: ${settled.map(esc).join(", ")} 🎉</p>` : ""}</section>
  <div class="actions"><a class="btn primary" href="#home">ホームへ</a><a class="btn" href="#lesson">今日のレッスン</a></div>`;
}

/* ---------- 添削 ---------- */
function vCorrect() {
  const pre = UI.correct && UI.correct.prefill ? UI.correct.prefill : ""; if (UI.correct) UI.correct.prefill = "";
  return `<h1>添削と再発防止</h1><p class="dim">書いた英文（日記・メール・会話の書き起こし）を貼ると、誤りを「指摘 → 訂正 → 避け方」で返す。範囲を絞るなら「冠詞だけ見て」のように指示を書く。</p>
  <section class="card"><textarea id="cr-text" rows="7" placeholder="英文を貼る">${esc(pre)}</textarea>
    <div class="row"><input id="cr-scope" placeholder="指示（任意）例: 冠詞だけ見て / 通じない誤りだけ"><button class="btn primary" data-action="do-correct">添削する</button><button class="btn" data-action="copy-prompt" data-kind="correct">プロンプトをコピー</button></div>
    <div id="cr-out"></div></section>`;
}
async function doCorrect() {
  const text = $("#cr-text").value.trim(), scope = $("#cr-scope").value.trim(), out = $("#cr-out"); if (!text) { toast("英文を入力してください"); return; }
  out.innerHTML = `<p class="dim">添削中…</p>`;
  const sys = `あなたは日本語話者向けの英語添削者です。${learnerContext()}\n学習者の英文を見直し、次の JSON だけを出力します（説明文や \`\`\` は不要）。分類は必ず次から選ぶ: ${MISTAKE_CATEGORIES.join(" / ")}。
事実としての誤り（errors）と、間違いではないがより自然な言い方（natural）を分ける。「why」はルールの言い直しではなく、次に同じ誤りを避けるチェックの仕方を1〜2文で。${scope ? `\n学習者の指示: 「${scope}」。この範囲以外は errors にも corrected にも反映しない。` : ""}
{"overall":"2文の全体評価。まず伝わっている点を具体的に褒め、次に一番効く改善点を1つ","errors":[{"original":"原文の該当部分","corrected":"訂正","cat":"分類","why":"なぜ・避け方"}],"corrected":"最小限の修正を施した全文","natural":[{"from":"原文","to":"より自然な言い方"}],"drill":[{"q":"最多分類の練習問題（穴埋め）","a":"答え"} ×3],"expressions":[{"en":"覚える価値のある表現","ja":"意味","ex":"例文"} 最大3]}`;
  try {
    const j = parseJSON(await callClaude(sys, [{ role: "user", content: text }]));
    UI.correct = { result: j };
    out.innerHTML = `<p class="big">${esc(j.overall)}</p>
    ${j.errors && j.errors.length ? `<table class="tbl"><thead><tr><th>#</th><th>原文</th><th>訂正</th><th>分類</th><th>なぜ・避け方</th></tr></thead><tbody>${j.errors.map((e, i) => `<tr><td>${i + 1}</td><td class="bad">${esc(e.original)}</td><td class="good">${esc(e.corrected)}</td><td><span class="pill">${esc(e.cat)}</span></td><td>${esc(e.why)}</td></tr>`).join("")}</tbody></table>` : `<p class="good">誤りはありませんでした。</p>`}
    <h4>訂正版</h4><p class="quote">${esc(j.corrected)} ${spk(j.corrected)}</p>
    ${j.natural && j.natural.length ? `<h4>より自然な言い方（間違いではない）</h4><ul>${j.natural.map((n) => `<li>${esc(n.from)} → <b>${esc(n.to)}</b></li>`).join("")}</ul>` : ""}
    ${j.drill && j.drill.length ? `<h4>今日の1ルール 練習</h4><ol>${j.drill.map((d) => `<li>${esc(d.q)} <details><summary>答え</summary>${esc(d.a)}</details></li>`).join("")}</ol>` : ""}
    <div class="actions"><button class="btn primary" data-action="save-correct">間違い ${(j.errors || []).length} 件と表現をログに保存</button></div>`;
  } catch (e) { out.innerHTML = apiErrorHtml(e); }
}
function saveCorrect() {
  const j = UI.correct && UI.correct.result; if (!j) return;
  for (const e of j.errors || []) addMistake(e.original, e.corrected, MISTAKE_CATEGORIES.includes(e.cat) ? e.cat : "その他", "correct");
  for (const x of (j.expressions || []).slice(0, 3)) addVocab("表現", x.en, x.ja, x.ex, "correct");
  addLog("correct", `添削（${(j.errors || []).length} 件）`, 8); save(); toast("保存しました"); $("[data-action=save-correct]").disabled = true;
}

/* ---------- 会話 / ロールプレイ（共通チャット） ---------- */
function chatSystem() {
  return `あなたは学習者の英語の会話パートナーです。${learnerContext()}
ルール:
- 最初の2往復は必ずとても簡単（L1: Yes/No で答えられる質問）から始める。正しく答えるたびに1段上げ、間違えたら同じ段、2回続けて詰まったら1段下げる。
  L1 Yes/No → L2 単語で答える5W1H → L3 1文で答える → L4 理由を求める → L5 2〜3文で意見 → L6 仮定・比較・経験
- 話題は日常の状況（食べ物を注文する、情報を尋ねる、雑談: 週末・天気・趣味・仕事）。1セッション1〜2場面。
- 学習者が詰まったり日本語で返したら、すぐ助ける: 答えの型を示し（"You can say: ..."）、同じ質問をもう一度する。責めない。
- 会話中は誤りを直さず、自分の返答の中で正しい形を自然に言い直す（リキャスト）。
- 返答は英語1〜3文（学習者のレベルに合わせて短く）。会話部分に日本語や解説を混ぜない。
- 返答の最後に必ず次の形式を付ける（訂正がなければ「なし 👍」）:
---
📝 Corrections
- 「原文」→「訂正」（一言理由・日本語）
📈 Level: L1〜L6
- 「もっと簡単に」「もっと難しく」と言われたらレベルを即座に変える。`;
}
function roleplaySystem(sc) {
  return `あなたは英語ロールプレイの相手役です。${learnerContext()}
場面: ${sc.title}。あなたの役: ${sc.role}。学習者の達成目標: ${sc.goal}。
ルール:
- 英語のみで、役として自然に話す。1回の発話は1〜3文。その場面で本当に使われる語彙・言い回しだけを使い、場面外の難語は出さない。
- 学習者が詰まったら役のまま助け舟を出す（選択肢を提示するなど）。誤りは直さず、返答の中で正しい形を自然に含める。
- 予定調和にしない。小さなトラブル（用意できていない、売り切れ など）を1つ入れて対応させる。
- 学習者が日本語で話したら "Sorry, I didn't catch that." のように英語で聞き返し、それでも詰まれば助け舟を出す。
- 最初の発話はあなたから、場面の冒頭のセリフで始める。
- 学習者が「終わり」「stop」「end」と言ったら、役を離れて "— End of role-play —" とだけ返す。`;
}
function chatView(kind) {
  const C = UI[kind];
  return `<div class="chatlog" id="chatlog">${C.msgs.map((m) => `<div class="msg ${m.role}">${m.role === "assistant" ? md(m.content) : esc(m.content)}${m.role === "assistant" ? spk(m.content.split("\n---")[0].replace(/\*\*/g, "")) : ""}</div>`).join("")}${C.busy ? `<div class="msg assistant dim">…</div>` : ""}</div>
  <form class="chatin" data-kind="${kind}" onsubmit="return false"><input id="chat-in" placeholder="英語で返す（分からなければ日本語でもOK）" autocomplete="off" ${C.busy ? "disabled" : ""}><button class="btn primary" data-action="chat-send" data-kind="${kind}" ${C.busy ? "disabled" : ""}>送る</button></form>
  <div class="actions sm"><button class="btn xs" data-action="chat-quick" data-kind="${kind}" data-text="もっと簡単に">もっと簡単に</button><button class="btn xs" data-action="chat-quick" data-kind="${kind}" data-text="もっと難しく">もっと難しく</button><button class="btn xs" data-action="chat-quick" data-kind="${kind}" data-text="分かりません。ヒントをください。">ヒント</button><button class="btn xs warnb" data-action="chat-end" data-kind="${kind}">終了してまとめる</button></div>`;
}
function vChat() {
  if (!UI.chat) UI.chat = { msgs: [], busy: false, summary: null };
  const C = UI.chat;
  if (C.summary) return summaryView("chat", C.summary);
  return `<h1>会話練習 <small>レベル別</small></h1><p class="dim">簡単な質問から始まり、正解するたびに難しくなる。詰まったら日本語で「分からない」と書けば助けてくれる。訂正は各返答の末尾にまとまる。</p>
  <section class="card">${C.msgs.length ? chatView("chat") : `<div class="actions"><button class="btn primary" data-action="chat-start" data-kind="chat">会話を始める</button><button class="btn" data-action="copy-prompt" data-kind="chat">プロンプトをコピー（API キーなしで使う）</button></div>`}</section>`;
}
function vRoleplay(args) {
  if (!UI.roleplay) UI.roleplay = { msgs: [], busy: false, summary: null, sc: null };
  const C = UI.roleplay;
  if (C.summary) return summaryView("roleplay", C.summary);
  if (C.sc && C.msgs.length) return `<h1>${esc(C.sc.title)} <small>あなた: 客側 / 相手: ${esc(C.sc.role)}</small></h1><p class="dim">目標: ${esc(C.sc.goal)}</p><section class="card">${chatView("roleplay")}</section>`;
  return `<h1>ロールプレイ <small>実践的な状況への没入</small></h1><p class="dim">相手役（フロント係・店員・面接官…）と場面に合った語彙だけで会話する。終了時に「最も役立つ表現リスト」と目標の達成判定が出る。</p>
  <div class="cards">${SCENARIOS.map((sc) => `<div class="lesson sel" data-action="rp-pick" data-id="${sc.id}"><b>${esc(sc.title)}</b><small>相手: ${esc(sc.role)} · フェーズ ${sc.phase}〜</small><p class="dim">${esc(sc.goal)}</p></div>`).join("")}</div>
  <section class="card"><h2>自由に場面を決める</h2><div class="row"><input id="rp-custom" placeholder="例: 美容院で髪型を注文する / 落とし物を駅で届ける"><button class="btn primary" data-action="rp-pick" data-id="custom">この場面で始める</button></div></section>
  <section class="card"><div class="actions"><button class="btn" data-action="copy-prompt" data-kind="roleplay">プロンプトをコピー（API キーなしで使う）</button></div></section>`;
}
function rpPick(id) {
  let sc = SCENARIOS.find((s) => s.id === id);
  if (id === "custom") { const t = $("#rp-custom").value.trim(); if (!t) { toast("場面を入力してください"); return; } sc = { id: "custom", title: t, role: "その場面の相手役", goal: "その場面で用件を達成する", vocab: [] }; }
  UI.roleplay = { msgs: [], busy: false, summary: null, sc };
  $("#view").innerHTML = `<h1>${esc(sc.title)}</h1><section class="card"><p><b>あなたの役:</b> 客・利用者側　<b>相手:</b> ${esc(sc.role)}</p><p><b>達成目標:</b> ${esc(sc.goal)}</p>
    ${sc.vocab.length ? `<h4>この場面の語彙</h4><ul class="plain">${sc.vocab.map((v) => `<li>${esc(v)} ${spk(v.replace(/（.*?）/g, ""))}</li>`).join("")}</ul>` : ""}
    <div class="actions"><button class="btn primary" data-action="chat-start" data-kind="roleplay">ロールプレイを始める</button><a class="btn" href="#roleplay" onclick="UI.roleplay=null">戻る</a></div></section>`;
}
async function chatStart(kind) {
  const C = UI[kind]; C.msgs = []; C.busy = true; render();
  try {
    const sys = kind === "chat" ? chatSystem() : roleplaySystem(C.sc);
    const first = kind === "chat" ? "（会話を始めてください。最初のあいさつと、とても簡単な質問を1つ）" : "（場面の冒頭のセリフから始めてください）";
    const reply = await callClaude(sys, [{ role: "user", content: first }]);
    C.msgs.push({ role: "assistant", content: reply });
  } catch (e) { C.msgs = []; C.busy = false; render(); $("#view .card").insertAdjacentHTML("afterbegin", apiErrorHtml(e)); return; }
  C.busy = false; render(); setTimeout(() => { const i = $("#chat-in"); if (i) i.focus(); }, 0);
}
async function chatSend(kind, text) {
  const C = UI[kind]; text = (text ?? $("#chat-in").value).trim(); if (!text || C.busy) return;
  C.msgs.push({ role: "user", content: text }); C.busy = true; render();
  try {
    const sys = kind === "chat" ? chatSystem() : roleplaySystem(C.sc);
    const reply = await callClaude(sys, C.msgs.map((m) => ({ role: m.role, content: m.content })));
    C.msgs.push({ role: "assistant", content: reply });
  } catch (e) { C.msgs.pop(); toast(e.message === "NO_KEY" ? "API キーが未設定です" : e.message); }
  C.busy = false; render(); setTimeout(() => { const i = $("#chat-in"); if (i) i.focus(); const l = $("#chatlog"); if (l) l.scrollTop = l.scrollHeight; }, 0);
}
async function chatEnd(kind) {
  const C = UI[kind]; if (!C.msgs.length) return; C.busy = true; render();
  const transcript = C.msgs.map((m) => `${m.role === "user" ? "学習者" : "相手"}: ${m.content}`).join("\n");
  const sys = `あなたは英語教師です。以下の${kind === "chat" ? "会話練習" : `ロールプレイ（場面: ${C.sc.title}、目標: ${C.sc.goal}）`}の記録を読み、次の JSON だけを出力します（説明や \`\`\` は不要）。分類は必ず次から: ${MISTAKE_CATEGORIES.join(" / ")}。
{"summary":"会話の要約と良かった点2つ（日本語）","achieved":[{"goal":"目標の要素","ok":true}],"corrections":[{"wrong":"学習者の原文","right":"訂正","cat":"分類","why":"一言"}] 最大5件・通じなくなる順,"expressions":[{"en":"役立つ表現（会話に実際に登場したもの）","ja":"意味","ex":"会話中の実例"}] ${kind === "chat" ? "最大5件" : "8〜12件"},"level":"${kind === "chat" ? "到達レベル L1〜L6" : "―"}","tip":"次にこの場面で言えると良い一言（英語と日本語）"}`;
  try { C.summary = parseJSON(await callClaude(sys, [{ role: "user", content: transcript }])); }
  catch (e) { toast(e.message); }
  C.busy = false; render();
}
function summaryView(kind, j) {
  return `<h1>${kind === "chat" ? "会話練習" : "ロールプレイ"} まとめ</h1>
  <section class="card"><p class="big">${esc(j.summary)}</p>${j.level && j.level !== "―" ? `<p>到達レベル: <b>${esc(j.level)}</b></p>` : ""}
    ${j.achieved && j.achieved.length && kind === "roleplay" ? `<h4>目標の達成</h4><ul class="plain">${j.achieved.map((a) => `<li>${a.ok ? '<span class="good">○</span>' : '<span class="bad">×</span>'} ${esc(a.goal)}</li>`).join("")}</ul>` : ""}
    ${j.corrections && j.corrections.length ? `<h4>訂正</h4><table class="tbl">${j.corrections.map((c) => `<tr><td class="bad">${esc(c.wrong)}</td><td class="good">${esc(c.right)}</td><td><span class="pill">${esc(c.cat)}</span> ${esc(c.why)}</td></tr>`).join("")}</table>` : `<p class="good">訂正はありませんでした。</p>`}
    ${j.expressions && j.expressions.length ? `<h4>最も役立つ単語と表現</h4><table class="tbl">${j.expressions.map((x) => `<tr><td><b>${esc(x.en)}</b> ${spk(x.en)}</td><td>${esc(x.ja)}</td><td><i>${esc(x.ex)}</i></td></tr>`).join("")}</table>` : ""}
    ${j.tip ? `<p class="quote">💡 ${esc(j.tip)}</p>` : ""}
    <div class="actions"><button class="btn primary" data-action="save-summary" data-kind="${kind}">表現と訂正をログに保存</button><button class="btn" data-action="chat-reset" data-kind="${kind}">保存せず終了</button></div></section>`;
}
function saveSummary(kind) {
  const C = UI[kind], j = C.summary;
  for (const x of (j.expressions || []).slice(0, kind === "chat" ? 5 : 12)) addVocab("表現", x.en, x.ja, x.ex, kind);
  for (const c of j.corrections || []) addMistake(c.wrong, c.right, MISTAKE_CATEGORIES.includes(c.cat) ? c.cat : "その他", kind);
  addLog(kind, kind === "chat" ? `会話練習（${j.level || ""}）` : `ロールプレイ: ${C.sc.title}`, 15);
  save(); UI[kind] = null; toast("保存しました"); location.hash = "#home";
}

/* ---------- 記録 ---------- */
function vProgress() {
  const stats = mistakeStats();
  return `<h1>記録</h1>
  <section class="card"><h2>間違いの分類 <small>${S.mistakes.length} 件</small></h2>${stats.length ? bars(stats) : `<p class="dim">まだありません。</p>`}</section>
  <section class="card"><h2>語彙・表現・文法 <small>${S.vocab.length} 件</small></h2>
    <div class="row"><input id="vf" placeholder="絞り込み" data-action="filter-vocab"></div>
    <div class="scroll"><table class="tbl" id="vocab-tbl"><thead><tr><th>種別</th><th>英語</th><th>意味</th><th>例文</th><th>Box</th><th>次回</th><th>出典</th><th></th></tr></thead><tbody>${vocabRows("")}</tbody></table></div></section>
  <section class="card"><h2>間違いログ</h2><div class="scroll"><table class="tbl"><thead><tr><th>日付</th><th>誤り</th><th>訂正</th><th>分類</th><th>出典</th></tr></thead><tbody>${S.mistakes.slice().reverse().slice(0, 100).map((m) => `<tr><td>${m.date}</td><td class="bad">${esc(m.wrong)}</td><td class="good">${esc(m.right)}</td><td>${esc(m.cat)}</td><td>${esc(m.source)}</td></tr>`).join("")}</tbody></table></div></section>
  <section class="card"><h2>学習の記録</h2><div class="scroll"><table class="tbl"><thead><tr><th>日付</th><th>種類</th><th>内容</th><th>分</th></tr></thead><tbody>${S.log.slice().reverse().slice(0, 100).map((l) => `<tr><td>${l.date}</td><td>${esc(l.kind)}</td><td>${esc(l.note)}</td><td>${l.minutes}</td></tr>`).join("")}</tbody></table></div></section>`;
}
function vocabRows(f) {
  f = norm(f);
  return S.vocab.slice().reverse().filter((v) => !f || norm(v.en + " " + v.ja + " " + v.kind).includes(f)).map((v) => `<tr><td>${esc(v.kind)}</td><td><b>${esc(v.en)}</b></td><td>${esc(v.ja)}</td><td><i>${esc(v.ex)}</i></td><td>${v.box}</td><td>${v.next}</td><td>${esc(v.source)}</td><td><button class="btn xs" data-action="del-vocab" data-id="${v.id}" title="削除">✕</button></td></tr>`).join("");
}

/* ---------- 設定 ---------- */
function vSettings() {
  return `<h1>設定</h1>
  <section class="card"><h2>学習者</h2>
    <div class="row"><label>現在のフェーズ</label><select id="st-phase">${PLAN.filter((p) => p.phase > 0).map((p) => `<option value="${p.phase}" ${p.phase === S.status.phase ? "selected" : ""}>${p.phase}. ${esc(p.title)}（${esc(p.level)}）</option>`).join("")}</select></div>
    <div class="row"><label>1日の学習時間（分）</label><input id="st-min" type="number" min="5" max="120" value="${S.status.minutesPerDay}"></div>
    <div class="row"><label>目標・興味（AI に渡す）</label><input id="st-goal" value="${esc(S.status.goal)}" placeholder="例: 来年の海外旅行で困らない / 仕事のメール"></div>
    <div class="row"><label>開始日</label><input id="st-start" type="date" value="${S.status.startDate || ""}"></div>
    <div class="actions"><button class="btn primary" data-action="save-settings">保存</button></div></section>
  <section class="card"><h2>Claude API <small>会話・ロールプレイ・添削・AIレッスンに必要</small></h2>
    <p class="dim">キーは <a href="https://console.anthropic.com/" target="_blank" rel="noopener">Anthropic Console</a> で取得する。<b>この端末のブラウザにだけ</b>保存され、送信先は api.anthropic.com のみ。共用の端末では使い終わったら消すこと。キーがなくても、各画面の「プロンプトをコピー」で Claude.ai や ChatGPT に貼って同じ練習ができる。</p>
    <div class="row"><label>API キー</label><input id="st-key" type="password" value="${esc(S.settings.apiKey)}" placeholder="sk-ant-..." autocomplete="off"></div>
    <div class="row"><label>モデル</label><select id="st-model">${MODELS.map(([v, l]) => `<option value="${v}" ${v === S.settings.model ? "selected" : ""}>${l}</option>`).join("")}</select></div>
    <div class="actions"><button class="btn primary" data-action="save-settings">保存</button><button class="btn" data-action="test-api">接続テスト</button><button class="btn" data-action="clear-key">キーを消す</button></div><div id="api-test"></div></section>
  <section class="card"><h2>データ</h2><p class="dim">学習データはこのブラウザの保存領域にある。別の端末に移すときや、リポジトリの <code>progress/*.md</code> に反映するときはエクスポートする。</p>
    <div class="actions"><button class="btn" data-action="export-json">JSON をエクスポート</button><label class="btn">JSON をインポート<input type="file" id="imp" accept="application/json" hidden></label><button class="btn" data-action="export-md">vocab-log.md / mistakes-log.md 形式で書き出す</button><button class="btn warnb" data-action="reset">すべて消去</button></div>
    <pre id="export-out" class="export" hidden></pre></section>`;
}
function saveSettings() {
  S.status.phase = +$("#st-phase").value; S.status.minutesPerDay = +$("#st-min").value || 20; S.status.goal = $("#st-goal").value.trim();
  S.status.startDate = $("#st-start").value || S.status.startDate || today();
  S.settings.apiKey = $("#st-key").value.trim(); S.settings.model = $("#st-model").value; save(); toast("保存しました");
}
async function testApi() {
  saveSettings(); const out = $("#api-test"); out.innerHTML = `<p class="dim">接続中…</p>`;
  try { const t = await callClaude("Reply with exactly: OK", [{ role: "user", content: "ping" }], { maxTokens: 50 }); out.innerHTML = `<p class="good">接続成功（応答: ${esc(t.trim().slice(0, 40))}）</p>`; }
  catch (e) { out.innerHTML = apiErrorHtml(e); }
}
function exportMd() {
  const v = ["# 語彙・表現・文法ログ（アプリから書き出し）", "", "| ID | 種別 | 英語 | 意味 | 例文 | 学習日 | Box | 次回復習 | 出典 |", "|----|------|------|------|------|--------|-----|----------|------|",
    ...S.vocab.map((x) => `| ${x.id} | ${x.kind} | ${x.en.replace(/\|/g, "／")} | ${x.ja.replace(/\|/g, "／")} | ${x.ex.replace(/\|/g, "／")} | ${x.learned} | ${x.box} | ${x.next} | ${x.source} |`)].join("\n");
  const m = ["# 間違いログ（アプリから書き出し）", "", "| 日付 | 誤り | 訂正 | 分類 | 出典 |", "|------|------|------|------|------|", ...S.mistakes.map((x) => `| ${x.date} | ${x.wrong.replace(/\|/g, "／")} | ${x.right.replace(/\|/g, "／")} | ${x.cat} | ${x.source} |`)].join("\n");
  const pre = $("#export-out"); pre.hidden = false; pre.textContent = v + "\n\n\n" + m; copyText(pre.textContent);
}
function exportJson() {
  const data = JSON.stringify(Object.assign({}, S, { settings: { apiKey: "", model: S.settings.model } }), null, 2);
  const blob = new Blob([data], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `english-learning-${today()}.json`; document.body.appendChild(a); a.click(); a.remove();
  const pre = $("#export-out"); pre.hidden = false; pre.textContent = data;
}
function importJson(file) {
  const r = new FileReader(); r.onload = () => { try { const j = JSON.parse(r.result); if (!Array.isArray(j.vocab)) throw new Error(); const key = S.settings.apiKey; S = Object.assign(defaultState(), j); if (!S.settings.apiKey) S.settings.apiKey = key; save(); toast("インポートしました"); render(); } catch (e) { toast("読み込めませんでした"); } }; r.readAsText(file);
}

/* ---------- プロンプトコピー（API なし運用） ---------- */
function buildPrompt(kind, theme) {
  const ctx = learnerContext();
  const vocabList = S.vocab.slice(-40).map((v) => `${v.en}（${v.ja}）`).join("、");
  const p = {
    chat: `${ctx}\n\n英語での会話のパートナーとして振る舞ってください。とても簡単なフレーズから始め、私が正解するたびに少しずつ難易度を上げてください。私が詰まったり間違えたりしたら、すぐに助けて正しい形を教えてください。日常生活の状況（食べ物を注文する、情報を尋ねる、おしゃべりする）について話題を振ってください。各回答の最後に私の間違いを修正してください。会話の途中で中断しないでください。`,
    roleplay: `${ctx}\n\n英語でロールプレイのシナリオを作成して、本物の状況を練習させてください：${theme || "[例：ホテルのチェックイン、就職面接、市場での買い物]"}。あなたは相手の役割を演じて、自然な感じで返事してください。その状況に合った語彙だけを使って、最後に登場した最も役立つ単語と表現のリストを教えてください。`,
    correct: `${ctx}\n\n次の英語の文章を見直し、文法、語彙、文構造のエラーを指摘してください。修正点を与えて、これらのエラーを避ける方法を説明してください。${theme ? `\n指示: ${theme}` : ""}\n\n---\n${($("#cr-text") || {}).value || "（ここに英文を貼る）"}`,
    lesson: `${ctx}\n\n英語の毎日のレッスンプランを作成し、以下を含めてください：語彙（6〜8語、発音記号と例文つき）、文の形成（型1つと例3つ）、発音ガイド（音1つ、口の形とミニマルペア）、短い実践演習（穴埋め5・並べ替え3・和文英訳3、解答は最後に）。合計15〜20分で終わる分量にしてください。テーマ: ${theme || "（テーマ）"}`,
    grammar: `${ctx}\n\n英語の文法「${theme || "（項目）"}」をシンプルに説明し、日常会話の例を使ってルールが実際どのように機能するかを示してください。理論的で抽象的な説明ではなく、一言ルール → 会話例（A/B） → 日本語話者がつまずく点（×→○） → 自分で3文作る空欄、の順で。`,
    review: `${ctx}\n\nすでに勉強した語彙とルール: ${vocabList || "（なし）"}\n\n上記に基づいて、学んだことを定着させるためのクイックレビュー・テストを作成してください。古い単語と新しい単語を混ぜて、穴埋めフレーズと双方向の翻訳を使用してください。最後に、私がまだ最も間違えやすい箇所を教えてください。`,
  }[kind];
  return p;
}

/* ---------- 簡易 Markdown ---------- */
function md(t) {
  return esc(t).replace(/^### (.*)$/gm, "<h4>$1</h4>").replace(/^## (.*)$/gm, "<h3>$1</h3>").replace(/^---$/gm, "<hr>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^- (.*)$/gm, "<li>$1</li>").replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`).replace(/\n{2,}/g, "<br><br>").replace(/\n/g, "<br>");
}

/* ===================== イベント ===================== */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]"); if (!el) return;
  const a = el.dataset.action, d = el.dataset;
  const map = {
    speak: () => speak(d.text),
    check: () => { const c = (S.checks[d.phase] = S.checks[d.phase] || {}); c[d.i] = el.checked; save(); },
    "set-phase": () => { S.status.phase = +d.phase; save(); toast(`フェーズ ${d.phase} を現在地にしました`); render(); },
    "gen-lesson": genLesson, "grade-lesson": gradeLesson, "finish-lesson": finishLesson,
    accept: () => { const i = +d.i, g = UI.lesson.graded; const w = g.wrong.find((x) => x.i === i); if (w) { g.wrong = g.wrong.filter((x) => x.i !== i); g.score++; } const ex = $(`.ex[data-i="${i}"]`); ex.classList.replace("ng", "ok"); ex.querySelector(".fb").innerHTML = `<span class="good">○（自己判定）</span>`; $("#lesson-result .big").textContent = `${g.score} / ${g.total} 正解`; },
    "own-to-correct": () => { const t = [...document.querySelectorAll("input.own")].map((i) => i.value.trim()).filter(Boolean).join("\n"); if (!t) { toast("まず文を書いてください"); return; } UI.correct = { prefill: t }; location.hash = "#correct"; },
    "learn-grammar": () => { const G = GRAMMAR.find((g) => g.id === d.id); addVocab("文法", G.title, G.rule, G.example, "grammar", GRAMMAR_CAT[G.id]); S.doneGrammar[G.id] = today(); addLog("grammar", G.title, 8); save(); toast("復習リストに登録しました"); location.hash = "#grammar"; },
    "ask-grammar": askGrammar,
    "start-review": startReview, "rv-answer": reviewAnswer, "rv-next": reviewNext, "rv-quit": reviewFinish,
    "rv-self": () => recordReview(d.ok === "1", $("#rv-in").value),
    "do-correct": doCorrect, "save-correct": saveCorrect,
    "chat-start": () => chatStart(d.kind), "chat-send": () => chatSend(d.kind), "chat-quick": () => chatSend(d.kind, d.text), "chat-end": () => chatEnd(d.kind),
    "chat-reset": () => { UI[d.kind] = null; render(); },
    "save-summary": () => saveSummary(d.kind),
    "rp-pick": () => rpPick(d.id),
    "del-vocab": () => { S.vocab = S.vocab.filter((v) => v.id !== +d.id); save(); render(); },
    "save-settings": saveSettings, "test-api": testApi,
    "clear-key": () => { S.settings.apiKey = ""; save(); render(); toast("キーを消しました"); },
    "export-json": exportJson, "export-md": exportMd,
    reset: () => { if (confirm("学習データをすべて消去します。元に戻せません。よろしいですか？")) { S = defaultState(); save(); render(); } },
    "copy-prompt": () => copyText(buildPrompt(d.kind, d.theme || ($("#rp-custom") || {}).value || ($("#cr-scope") || {}).value || "")),
  };
  if (map[a]) map[a]();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  if (e.target.id === "chat-in") { e.preventDefault(); chatSend(e.target.closest("form").dataset.kind); }
  else if (e.target.id === "rv-in") { e.preventDefault(); const b = $("[data-action=rv-answer]"); if (b && !b.disabled) reviewAnswer(); else { const n = $("[data-action=rv-next]"); if (n) reviewNext(); } }
  else if (e.target.id === "gen-theme") genLesson();
  else if (e.target.id === "gq") askGrammar();
  else if (e.target.id === "rp-custom") rpPick("custom");
});
document.addEventListener("input", (e) => { if (e.target.id === "vf") $("#vocab-tbl tbody").innerHTML = vocabRows(e.target.value); });
document.addEventListener("change", (e) => { if (e.target.id === "imp" && e.target.files[0]) importJson(e.target.files[0]); });
window.addEventListener("hashchange", () => { if (UI.review && UI.review.active && location.hash !== "#review") UI.review.active = false; render(); });
load(); render();
