// 接続部（自動売買）のシナリオ試験。EA 全体を C++ に写したもの（conncheck.py の出力）を、状態を持つ API の模擬（conn_mock.h）で動かす。
//   python3 conncheck.py ../FX_Fusion_EA.mq5 conn_check.cpp && g++ -std=c++17 -o conntest conntest.cpp && ./conntest
// 確かめること（2巡目のレビューの所見）:
//   R2-01 約定してすぐ SL で閉じても、同じ足で同じセットアップに入り直さない
//   R2-02 同じ取引を _real.csv に2回書かない
//   R2-03 監視の権利を失ったら止まる。持ち主の生存記録が無いだけでは権利を奪わない
//   R2-04 停止の間に決済足を過ぎた建玉は、引き継いだらすぐ決済する
//   R2-05 市場が閉まっている（MARKET_CLOSED）間は決済を送り続けず、【要対応】も送らない
//   R2-06 開いている建玉の初期 SL のグローバル変数を消さない
//   R2-07 一部約定した注文を取消したら、新しい注文を出さない
//   R2-08 建玉が2本あっても、開いている建玉を決済済みとして記録しない
//   R2-09 管理していない FUSION の注文・建玉を数えて知らせる
//   R2-14 同じ見送りの通知を繰り返さない
//   R2-17 成行が受け付け後に拒否され続けても、出すのは1つの足で2回まで
//   R2-19 決済を送る直前に SL で閉じた建玉は、理由を SL として記録する
// 模擬の振る舞いは試験が決めたもので、MT5 の本当の振る舞いの確認にはならない（デモ口座での確認は別に要る）。
#define CONN_MOCK 1
#include "conn_check.cpp"

static int g_fail = 0, g_pass = 0;
#define CHECK(cond, msg) do { if(cond) g_pass++; else { g_fail++; printf("  NG: %s（%s:%d）\n", msg, __FILE__, __LINE__); } } while(0)

static datetime T(int y, int mo, int d, int h, int mi = 0) {
  MqlDateTime s; memset(&s, 0, sizeof s); s.year = y; s.mon = mo; s.day = d; s.hour = h; s.min = mi; return StructToTime(s);
}

static int count_notify(const string& sub) {
  int n = 0;
  for(int i = 0; i < g_nq; i++) if(g_queue[i].find(sub) != string::npos) n++;
  return n;
}

static int real_rows() {
  string& f = W.files["FusionEA\\EURUSD_real.csv"];
  int n = 0; for(char ch : f) if(ch == '\n') n++;
  return n > 0 ? n - 1 : 0;                          // ヘッダーを除く
}

static string last_real_row() {
  string f = W.files["FusionEA\\EURUSD_real.csv"];
  if(f.size() < 2) return "";
  size_t e = f.size() - 2; size_t b = f.rfind('\n', e); return f.substr(b == string::npos ? 0 : b + 1, e - (b == string::npos ? 0 : b + 1) + 1);
}

static void advance(uint ms) { W.ms += ms; W.now += (datetime)(ms / 1000); }

//--- 平日の H1 足を from から to の手前まで作る（土日は作らない）
static CSymbolCtx* setup(datetime from, datetime to, datetime now) {
  W = MockWorld();
  W.now = now;
  g_tester = false; g_conn = true; g_connSinceMs = 0; g_nq = 0; ArrayResize(g_queue, 0); ArrayResize(g_qPrio, 0); ArrayResize(g_qMs, 0);
  g_tradeNote = ""; g_token = 1.0; g_hbMs = 0; g_logs = true;
  InpAutoTrade = true;
  g_trade.SetExpertMagicNumber((ulong)InpMagicNumber);
  CSymbolCtx* c = new CSymbolCtx();
  c->sym = "EURUSD"; c->base = "EURUSD"; c->tag = "EURUSD"; c->digits = 5; c->point = 0.00001; c->pip = 0.0001;
  c->lockName = LockName(c);
  SFusionParams p; FillParams(p, c);
  c->eng.Configure(p, InpExtraClosedDays, InpExtraEarlyDays);
  MqlArray<MqlRates> r;
  double px = 1.1000; unsigned seed = 12345;
  for(datetime t = from; t < to; t += 3600) {
    MqlDateTime s; TimeToStruct(t, s);
    if(s.day_of_week == 0 || s.day_of_week == 6) continue;
    seed = seed * 1103515245u + 12345u; double step = ((double)((seed >> 8) % 2001) - 1000.0) * 1e-6;
    MqlRates b; memset(&b, 0, sizeof b); b.time = t; b.open = px; px += step; b.close = px;
    b.high = std::max(b.open, b.close) + 0.0003; b.low = std::min(b.open, b.close) - 0.0003; r.v.push_back(b);
  }
  c->eng.Load(r, (int)r.v.size());
  c->ready = true; c->locked = true; c->loads = 1;
  c->lastForming = c->eng.m_T[c->eng.m_n - 1] + 3600;
  ArrayResize(g_ctx, 1); g_ctx[0] = c; g_nctx = 1;
  return c;
}

static CSymbolCtx* setup_mid() { return setup(T(2024, 2, 5, 0), T(2024, 3, 13, 10), T(2024, 3, 13, 10, 5)); }   // 水曜 10:05（形成中は 10:00 の足）

//--- 置きたい注文（買い。key は最後の確定足の 10 本前）
static void want_buy(CSymbolCtx* c, int back = 10, double price = 1.10100, double sl = 1.09900) {
  int k = c->eng.m_n - 1 - back;
  SSetup s; FE_SetupClear(s);
  s.dir = 1; s.key_idx = k; s.key_time = c->eng.m_T[k]; s.price = price; s.sl = sl; s.atr = 0.0010; s.score = 60; s.pattern = 1;
  s.R = price - sl; s.tp1 = price + 0.003;
  c->real.want = true; c->real.wantSetup = s; c->real.barDue = false;
}

//--- 待機注文が約定する（close_now なら、同じ時刻のうちに SL で閉じる）。建玉 ID は注文番号と同じ
static void fill_order(ulong t, bool close_now, double exit_px, bool show_pos = true) {
  for(size_t i = 0; i < W.orders.size(); i++) if(W.orders[i].ticket == t) {
    MockOrder o = W.orders[i]; W.orders.erase(W.orders.begin() + (long)i);
    o.state = ORDER_STATE_FILLED; o.vc = 0.0; o.pos_id = (long)t; W.hist_orders.push_back(o);
    long dir = (o.type == ORDER_TYPE_BUY_STOP) ? 1 : -1;
    mock_add_deal(t, (long)t, o.sym, o.magic, DEAL_ENTRY_IN, dir == 1 ? DEAL_TYPE_BUY : DEAL_TYPE_SELL, DEAL_REASON_EXPERT, o.price, o.vi, 0.0, o.cmt);
    if(close_now)
      mock_add_deal(0, (long)t, o.sym, o.magic, DEAL_ENTRY_OUT, dir == 1 ? DEAL_TYPE_SELL : DEAL_TYPE_BUY, DEAL_REASON_SL, exit_px, o.vi,
                    (exit_px - o.price) * dir * o.vi * 100000.0, "");
    else if(show_pos)
      W.positions.push_back(MockPos{t, (long)t, o.sym, o.magic, dir == 1 ? POSITION_TYPE_BUY : POSITION_TYPE_SELL, o.vi, o.price, o.sl, W.now, o.cmt});
    return;
  }
  printf("  (fill_order: 注文 %llu がない)\n", (unsigned long long)t);
}

static void add_position(ulong t, datetime when, double price, double sl, long magic, const string& cmt) {
  W.positions.push_back(MockPos{t, (long)t, "EURUSD", magic, POSITION_TYPE_BUY, 0.10, price, sl, when, cmt});
  mock_add_deal(t, (long)t, "EURUSD", magic, DEAL_ENTRY_IN, DEAL_TYPE_BUY, DEAL_REASON_EXPERT, price, 0.10, 0.0, cmt);
}

static void cycles(CSymbolCtx* c, int n, uint step = 5000) { for(int i = 0; i < n; i++) { advance(step); RealService(c); } }

static void test_flash_no_reentry() {
  printf("R2-01 約定してすぐ SL で閉じたら、同じ足で入り直さない\n");
  CSymbolCtx* c = setup_mid();
  want_buy(c);
  RealService(c);
  CHECK(W.n_buystop == 1 && c->real.ordTicket != 0, "逆指値を1つ置く");
  ulong t = c->real.ordTicket;
  fill_order(t, true, 1.09900);
  cycles(c, 8);
  CHECK(W.n_buystop == 1 && W.n_market == 0, "同じ足で置き直さない（成行も出さない）");
  CHECK(c->real.nTrades == 1 && real_rows() == 1, "約定→すぐ決済を1回だけ記録する");
  CHECK(c->real.cons.Has(1, c->real.wantSetup.key_idx), "約定済み集合に入れる（R06）");
  CHECK(count_notify("→すぐ決済 SL") == 1, "約定→すぐ決済を1回通知する");
  CHECK(last_real_row().find(",SL,") != string::npos, "決済理由は SL");
  //--- 次の足：同じ key は R06 で置かない（最後の確認）
  want_buy(c);
  cycles(c, 3);
  CHECK(W.n_buystop == 1 && !c->real.want, "約定済みの key には次の足でも置かない");
}

static void test_no_double_record(bool resolveAfterExit) {
  printf("R2-02 建玉を見てから閉じても、_real.csv に2回書かない（%s）\n", resolveAfterExit ? "約定の確認が決済の記録より後" : "約定の確認と決済の記録が同じ巡回");
  CSymbolCtx* c = setup_mid();
  want_buy(c);
  RealService(c);
  ulong t = c->real.ordTicket;
  W.hist_lag = true;                                   // 注文の履歴はまだ見えない
  fill_order(t, false, 0.0);
  advance(5000); RealService(c);
  CHECK(c->real.posTicket == t, "建玉を追い始める");
  CHECK(count_notify("約定 ") == 1, "約定を通知する");
  mock_close_position(t, 1.09900, DEAL_REASON_SL);
  if(!resolveAfterExit) W.hist_lag = false;
  advance(5000); RealService(c);
  if(resolveAfterExit) { W.hist_lag = false; }
  cycles(c, 8);
  CHECK(c->real.nTrades == 1 && real_rows() == 1, "記録は1行だけ");
  CHECK(count_notify("決済 SL") == 1 && count_notify("すぐ決済") == 0, "決済の通知は1回だけ");
  CHECK(W.n_buystop == 1, "置き直さない");
}

static void test_two_positions() {
  printf("R2-08 建玉が2本あっても、開いている建玉を決済済みにしない\n");
  CSymbolCtx* c = setup_mid();
  add_position(6001, W.now - 600, 1.10100, 1.09900, InpMagicNumber, "FC1_0");
  RealService(c);
  CHECK(c->real.posTicket == 6001, "建玉 A を引き継ぐ");
  add_position(6002, W.now, 1.10200, 1.10000, InpMagicNumber, "FC1_0");
  cycles(c, 10);
  advance(31000); RealService(c); RealService(c);
  CHECK(c->real.posTicket == 6001, "追っている建玉 A を追い続ける");
  CHECK(c->real.nTrades == 0 && real_rows() == 0, "開いている建玉を決済済みとして記録しない");
  CHECK(count_notify("建玉が 2 本") == 1, "2本あることを1回だけ知らせる");
}

static void test_close_reason(bool gone) {
  printf("R2-19 決済の理由（%s）\n", gone ? "送る直前に SL で閉じていた→SL" : "EA が決済した→WEEKEND");
  CSymbolCtx* c = setup_mid();
  add_position(6001, W.now - 600, 1.10100, 1.09900, InpMagicNumber, "FC1_0");
  RealService(c);
  RequestClose(c, XR_WEEKEND, "試験");
  W.close_gone = gone;
  cycles(c, 4);
  CHECK(c->real.posTicket == 0 && c->real.closeReq == 0, "建玉がなくなり、決済の要求を終える");
  CHECK(real_rows() == 1, "1行記録する");
  string row = last_real_row();
  CHECK(row.find(gone ? ",SL," : ",WEEKEND,") != string::npos, gone ? "理由は SL（WEEKEND ではない）" : "理由は WEEKEND");
}

static void test_market_closed() {
  printf("R2-05 市場が閉まっている間は決済を送り続けない\n");
  CSymbolCtx* c = setup_mid();
  add_position(6001, W.now - 600, 1.10100, 1.09900, InpMagicNumber, "FC1_0");
  RealService(c);
  RequestClose(c, XR_WEEKEND, "試験");
  W.fail_close = TRADE_RETCODE_MARKET_CLOSED;
  RealService(c);
  CHECK(W.n_close == 1, "1回送る");
  cycles(c, 60, 10000);                                // 10分（新しいティックなし）
  CHECK(W.n_close == 1, "新しいティックが来るまで送らない");
  cycles(c, 130, 10000);                               // さらに約22分：30分たったら1回だけ確かめる
  CHECK(W.n_close == 2, "30分たったら1回確かめる");
  CHECK(count_notify("市場が閉まっているため") == 1, "市場が閉まっていることを1回だけ知らせる");
  CHECK(count_notify("【要対応】") == 0, "【要対応】は送らない（手動でも決済できない）");
  W.fail_close = 0; W.tick_msc += 1000;                // 取引が再開した
  cycles(c, 3);
  CHECK(W.n_close == 3 && W.positions.empty(), "再開したらすぐ決済する");
  CHECK(last_real_row().find(",WEEKEND,") != string::npos, "理由は WEEKEND");
  CHECK(count_notify("決済できました") == 1, "決済できたことを知らせる");
}

static void test_missed_weekend() {
  printf("R2-04 停止の間に決済足を過ぎた建玉は、引き継いだらすぐ決済する\n");
  CSymbolCtx* c = setup(T(2024, 2, 5, 0), T(2024, 3, 11, 2), T(2024, 3, 11, 2, 30));   // 月曜 02:30（最後の確定足は 01:00）
  add_position(6001, T(2024, 3, 8, 21, 30), 1.10100, 1.09900, InpMagicNumber, "FC1_0");   // 金曜 21:30 に約定した建玉
  RealService(c);
  CHECK(c->real.posTicket == 0 || c->real.closeReq != 0 || W.positions.empty(), "決済を要求する");
  CHECK(W.n_close >= 1 && W.positions.empty(), "すぐ決済する");
  CHECK(count_notify("決済足の確定") == 1, "経緯（決済足を過ぎた）を知らせる");
  cycles(c, 3);
  CHECK(last_real_row().find(",WEEKEND,") != string::npos, "理由は WEEKEND");
  //--- 決済足より後の建玉（月曜 00:30）は決済しない
  CSymbolCtx* c2 = setup(T(2024, 2, 5, 0), T(2024, 3, 11, 2), T(2024, 3, 11, 2, 30));
  add_position(6002, T(2024, 3, 11, 0, 30), 1.10100, 1.09900, InpMagicNumber, "FC1_0");
  RealService(c2);
  CHECK(W.n_close == 0 && c2->real.posTicket == 6002, "決済足より後の建玉は決済しない");
}

static void test_partial_cancel() {
  printf("R2-07 一部約定した注文を取消したら、新しい注文を出さない\n");
  CSymbolCtx* c = setup_mid();
  want_buy(c);
  RealService(c);
  ulong t = c->real.ordTicket;
  W.orders[0].vc = W.orders[0].vi / 2.0;              // 一部約定（建玉はまだ見えない）
  want_buy(c, 5, 1.10120, 1.09920);                    // 別の key に置き換えたい
  advance(5000); RealService(c);
  CHECK(W.n_buystop == 1, "新しい注文は出さない");
  CHECK(c->real.chkTicket == t || c->real.fillPosId != 0 || !c->real.want, "約定として扱う");
}

static void test_lock() {
  printf("R2-03 監視の権利\n");
  CSymbolCtx* c = setup_mid();
  W.gv[c->lockName] = 999.0;                           // 別のチャートが権利を取った
  g_hbMs = 0; Heartbeats();
  CHECK(!c->locked && !c->ready, "権利を失ったら、その銘柄の処理を止める");
  CHECK(count_notify("監視の権利を別のチャート") == 1, "知らせる");
  //--- 挑戦する側：生存記録が無いだけでは奪わない。2回続けて変わらなければ奪う
  CSymbolCtx* d = setup_mid();
  d->locked = false;
  W.gv[d->lockName] = 999.0;
  CHECK(!AcquireLock(d, true), "起動時：生存記録が無ければ奪わない");
  CHECK(!AcquireLock(d, false), "巡回：1回目は奪わない");
  advance(60000);
  CHECK(!AcquireLock(d, false), "巡回：2回目（1分）も奪わない");
  advance(60000);
  CHECK(AcquireLock(d, false), "巡回：2回続けて変わらなければ奪う");
  //--- 生存記録が動いていれば奪わない
  CSymbolCtx* e = setup_mid();
  e->locked = false;
  W.gv[e->lockName] = 999.0;
  W.gv[e->lockName + "H"] = 100.0;
  AcquireLock(e, false);
  for(int i = 0; i < 4; i++) { advance(60000); W.gv[e->lockName + "H"] += 60.0; CHECK(!AcquireLock(e, false), "生存記録が動いていれば奪わない"); }
}

static void test_market_rejects() {
  printf("R2-17 成行が受け付け後に拒否され続けても、1つの足で2回まで\n");
  CSymbolCtx* c = setup_mid();
  c->lastForming = W.now - 60;
  W.ask = 1.10150; W.bid = 1.10140;                    // すでに逆指値を越えている → 成行
  W.market_reject = true;
  want_buy(c);
  cycles(c, 10);
  CHECK(W.n_market == 2, "成行は2回まで");
  CHECK(count_notify("成行を 2 回出したが約定しなかった") == 1, "見送りを1回だけ知らせる");
  CHECK(count_notify("成行 ") == 0, "受け付けただけでは成行を通知しない");
  CHECK(!c->real.want, "この足は見送る");
}

static void test_skip_dedupe() {
  printf("R2-14 同じ見送りの通知を繰り返さない\n");
  CSymbolCtx* c = setup_mid();
  W.balance = 10.0;                                    // 最小ロットでもリスクが目標を大きく超える
  for(int bar = 0; bar < 3; bar++) { want_buy(c); RetryReset(c); advance(3600000); RealService(c); }
  CHECK(count_notify("最小ロットでも") == 1, "同じセットアップ・同じ理由は1回だけ通知する");
  CHECK(W.n_buystop == 0, "発注しない");
}

static void test_isl_gvs() {
  printf("R2-06 開いている建玉の初期 SL を消さない\n");
  CSymbolCtx* c = setup_mid();
  W.positions.push_back(MockPos{7001, 7001, "EURUSD", InpMagicNumber, POSITION_TYPE_BUY, 0.1, 1.1, 1.09, W.now, "FC1_0"});
  mock_add_deal(0, 7002, "EURUSD", InpMagicNumber, DEAL_ENTRY_OUT, DEAL_TYPE_SELL, DEAL_REASON_SL, 1.09, 0.1, -10.0, "");
  for(long id = 7001; id <= 7004; id++) GlobalVariableSet(GvIsl(c, id), 1.09);
  W.gv_time[GvIsl(c, 7004)] = W.now - 40 * 86400;
  c->real.posId = 0;
  CleanIslGvs(c);
  CHECK(GlobalVariableCheck(GvIsl(c, 7001)), "開いている建玉（まだ追っていない）のものは残す");
  CHECK(!GlobalVariableCheck(GvIsl(c, 7002)), "閉じたことを確かめた建玉のものは消す");
  CHECK(GlobalVariableCheck(GvIsl(c, 7003)), "確かめられない新しいものは残す");
  CHECK(!GlobalVariableCheck(GvIsl(c, 7004)), "確かめられない古いもの（30日超）は消す");
}

static void test_foreign() {
  printf("R2-09 管理していない FUSION の注文・建玉を知らせる\n");
  setup_mid();
  W.orders.push_back(MockOrder{8001, "GBPUSD", 999, ORDER_TYPE_BUY_STOP, ORDER_STATE_PLACED, 0.1, 0.1, 1.3, 1.29, "FC1_1700000000", 0});
  W.positions.push_back(MockPos{8002, 8002, "EURUSD", InpMagicNumber, POSITION_TYPE_BUY, 0.1, 1.1, 1.09, W.now, "FC1_1700000000"});
  WarnForeignOrders();
  CHECK(count_notify("管理していない FUSION の注文 1 件・建玉 0 件") == 1, "別のマジック・監視していない銘柄の注文を数える（自分の建玉は数えない）");
  W.gv[LockNameOf(999, "GBPUSD")] = 777.0;             // 別のチャートの EA（マジック 999）が監視中
  WarnForeignOrders();
  CHECK(count_notify("管理していない") == 1, "別のチャートが監視している銘柄は数えない");
  InpAutoTrade = false;                                // 自動売買を OFF にした：自分の建玉も管理されない
  WarnForeignOrders();
  CHECK(count_notify("注文 0 件・建玉 1 件") == 1, "自動売買 OFF なら自分の建玉も数える");
  InpAutoTrade = true;
}

static void test_r06_guard() {
  printf("R2-01 約定済みの key には、最後の確認で置かない\n");
  CSymbolCtx* c = setup_mid();
  RealService(c);                                      // 口座の引き継ぎ（約定済み集合を約定履歴から作り直す）を先に済ませる
  want_buy(c);
  c->real.cons.Add(1, c->real.wantSetup.key_idx);
  advance(5000); RealService(c);
  CHECK(W.n_buystop == 0 && !c->real.want, "置かない");
}

int main() {
  test_flash_no_reentry();
  test_r06_guard();
  test_no_double_record(false);
  test_no_double_record(true);
  test_two_positions();
  test_close_reason(true);
  test_close_reason(false);
  test_market_closed();
  test_missed_weekend();
  test_partial_cancel();
  test_lock();
  test_market_rejects();
  test_skip_dedupe();
  test_isl_gvs();
  test_foreign();
  printf("CONN TEST %s（%d 件合格、%d 件不合格）\n", g_fail == 0 ? "OK" : "NG", g_pass, g_fail);
  return g_fail == 0 ? 0 : 1;
}
