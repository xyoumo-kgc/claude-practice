// 接続部のシナリオ試験（conntest.cpp）用の MQL5 API の模擬。注文・建玉・約定履歴・グローバル変数・ファイル・時計を持つ。
// conn_shim.h の「動かない代用」と同じ関数を、状態を持つ形で定義する（CONN_MOCK を定義したときだけ使う）。
// 実際の MT5 の振る舞い（約定の順序、履歴の遅れ、拒否）は試験が W を書き換えて作る。MT5 の本当の振る舞いの確認にはならない。
#pragma once
#include <map>
#include <sstream>

struct MockOrder { ulong ticket; string sym; long magic; long type; long state; double vi, vc, price, sl; string cmt; long pos_id; };
struct MockPos { ulong ticket; long id; string sym; long magic; long type; double vol, price, sl; datetime time; string cmt; };
struct MockDeal { ulong ticket; ulong order; long pos_id; string sym; long magic; long entry; long type; long reason;
                  double price, vol, profit, swap, comm; datetime time; string cmt; };

struct MockWorld {
  std::vector<MockOrder> orders;        // 有効な待機注文
  std::vector<MockOrder> hist_orders;   // 履歴の注文
  std::vector<MockPos> positions;
  std::vector<MockDeal> deals;
  std::vector<ulong> sel_deals;         // HistorySelect・HistorySelectByPosition で選んだ約定
  int sel_order = -1;
  int sel_pos = -1;
  ulong next_ticket = 5000;
  ulong next_deal = 90000;
  uint ms = 100000;                     // GetTickCount
  datetime now = 0;                     // TimeCurrent・TimeTradeServer・TimeLocal・TimeGMT
  double bid = 1.10000, ask = 1.10010;
  long tick_msc = 1;
  double balance = 10000.0;
  std::map<string, double> gv;
  std::map<string, datetime> gv_time;
  std::map<string, string> files;
  std::vector<string> handles;          // FileOpen のハンドル → 名前
  std::vector<string> log;              // Print・PrintFormat・Alert の出力
  // 振る舞いの注入
  bool hist_lag = false;                // 履歴の注文がまだ見えない（HistoryOrderSelect が false）
  bool market_reject = false;           // 成行を受け付けた（PLACED）後に拒否される
  bool close_gone = false;              // 決済を送る直前に SL で閉じていた（PositionClose は失敗）
  uint fail_send = 0, fail_delete = 0, fail_close = 0, fail_modify = 0, fail_posmod = 0;   // 0 以外ならその戻りコードで失敗
  int n_buystop = 0, n_sellstop = 0, n_market = 0, n_close = 0, n_delete = 0, n_modify = 0;
};
static MockWorld W;

inline MockOrder* mock_order(ulong t) { for(auto& o : W.orders) if(o.ticket == t) return &o; return nullptr; }
inline MockOrder* mock_hist_order(ulong t) { for(auto& o : W.hist_orders) if(o.ticket == t) return &o; return nullptr; }
inline MockPos* mock_pos(ulong t) { for(auto& p : W.positions) if(p.ticket == t) return &p; return nullptr; }
inline MockDeal* mock_deal(ulong t) { for(auto& d : W.deals) if(d.ticket == t) return &d; return nullptr; }
inline void mock_add_deal(ulong order, long pid, const string& sym, long magic, long entry, long type, long reason, double price, double vol,
                          double profit, const string& cmt) {
  MockDeal d{W.next_deal++, order, pid, sym, magic, entry, type, reason, price, vol, profit, 0.0, 0.0, W.now, cmt};
  W.deals.push_back(d);
}

long AccountInfoInteger(ENUM_ACCOUNT_INFO_INTEGER p) { return p == ACCOUNT_LOGIN ? 12345678 : 1; }
double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE p) { return p == ACCOUNT_BALANCE ? W.balance : 1e9; }
int MQLInfoInteger(ENUM_MQL_INFO_INTEGER p) { return p == MQL_TRADE_ALLOWED ? 1 : 0; }
int TerminalInfoInteger(ENUM_TERMINAL_INFO_INTEGER p) { return p == TERMINAL_MAXBARS ? 100000 : 1; }
long SeriesInfoInteger(const string&, ENUM_TIMEFRAMES, ENUM_SERIES_INFO_INTEGER p) { return p == SERIES_SYNCHRONIZED ? 1 : 0; }
long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER p) {
  switch(p) { case SYMBOL_DIGITS: return 5; case SYMBOL_EXPIRATION_MODE: return SYMBOL_EXPIRATION_GTC;
              case SYMBOL_TRADE_MODE: return SYMBOL_TRADE_MODE_FULL; default: return 0; }
}
double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE p) {
  switch(p) { case SYMBOL_ASK: return W.ask; case SYMBOL_BID: return W.bid; case SYMBOL_POINT: return 0.00001;
              case SYMBOL_TRADE_TICK_SIZE: return 0.00001; case SYMBOL_TRADE_TICK_VALUE: return 1.0; case SYMBOL_VOLUME_MAX: return 100.0;
              case SYMBOL_VOLUME_MIN: return 0.01; case SYMBOL_VOLUME_STEP: return 0.01; }
  return 0.0;
}
bool SymbolInfoTick(const string&, MqlTick& t) { t.time = W.now; t.bid = W.bid; t.ask = W.ask; t.last = 0; t.volume = 0; t.time_msc = W.tick_msc;
                                                 t.flags = 0; t.volume_real = 0; return true; }
bool SymbolSelect(const string&, bool) { return true; }
long ChartID() { return 1; }
long ChartGetInteger(long, ENUM_CHART_PROPERTY_INTEGER, int = 0) { return 0; }
void ChartRedraw(long = 0) {}
template<class T> ENUM_POINTER_TYPE CheckPointer(T*) { return POINTER_DYNAMIC; }
int Bars(const string&, ENUM_TIMEFRAMES) { return 0; }
int Bars(const string&, ENUM_TIMEFRAMES, datetime, datetime) { return 0; }
int CopyRates(const string&, ENUM_TIMEFRAMES, int, int, MqlArray<MqlRates>&) { return 0; }
int CopyTime(const string&, ENUM_TIMEFRAMES, int, int, MqlArray<datetime>&) { return 0; }
datetime iTime(const string&, ENUM_TIMEFRAMES, int) { return 0; }
double iOpen(const string&, ENUM_TIMEFRAMES, int) { return 0; }
bool EventSetTimer(int) { return true; }
void EventKillTimer() {}
int GetLastError() { return 0; }
void ResetLastError() {}
ulong GetMicrosecondCount() { return 0; }
uint GetTickCount() { return W.ms; }
datetime TimeCurrent() { return W.now; }
datetime TimeGMT() { return W.now - 2 * 3600; }
datetime TimeLocal() { return W.now; }
datetime TimeTradeServer() { return W.now; }
inline double MathRound(double v) { return std::floor(v + 0.5); }
inline double MathPow(double b, double e) { return std::pow(b, e); }
inline double NormalizeDouble(double v, int d) { double m = std::pow(10.0, d); return std::round(v * m) / m; }
inline string ShortToString(ushort ch) { return string(1, (char)ch); }
inline int StringCompare(const string& a, const string& b, bool = true) { return a.compare(b); }
inline string mock_str(const string& s) { return s; }
inline string mock_str(const char* s) { return s; }
template<class T> string mock_str(T v) { std::ostringstream o; o << v; return o.str(); }
template<class... A> void Print(A... a) { string s; using ex = int[]; (void)ex{0, ((void)(s += mock_str(a)), 0)...}; W.log.push_back(s); }
template<class... A> void Alert(A... a) { Print(a...); }
template<class... A> void PrintFormat(const string& f, A... a) { W.log.push_back(StringFormat(f, a...)); }
bool SendNotification(const string&) { return true; }
int FileOpen(const string& name, int flags, short = '\t', uint = CP_ACP) {
  if(!(flags & FILE_READ) || !W.files.count(name))
    W.files[name] = "";                 // 書き込みだけで開く＝作り直す。読み書きで開く＝あれば続きに書く
  W.handles.push_back(name);
  return (int)W.handles.size() - 1;
}
void FileClose(int) {}
void FileFlush(int) {}
uint FileWriteString(int h, const string& s, int = -1) { W.files[W.handles[h]] += s; return (uint)s.size(); }
ulong FileSize(int h) { return W.files[W.handles[h]].size(); }
bool FileSeek(int, long, ENUM_FILE_POSITION) { return true; }
bool FileIsExist(const string& n, int = 0) { return W.files.count(n) > 0; }
bool FileDelete(const string& n, int = 0) { return W.files.erase(n) > 0; }
bool FileMove(const string& a, int, const string& b, int) { if(!W.files.count(a)) return false; W.files[b] = W.files[a]; W.files.erase(a); return true; }
long FileFindFirst(const string&, string&, int = 0) { return -1; }
bool FileFindNext(long, string&) { return false; }
void FileFindClose(long) {}
bool FolderCreate(const string&, int = 0) { return true; }
bool FolderClean(const string&, int = 0) { return true; }
bool FolderDelete(const string&, int = 0) { return true; }
bool GlobalVariableCheck(const string& n) { return W.gv.count(n) > 0; }
bool GlobalVariableDel(const string& n) { W.gv_time.erase(n); return W.gv.erase(n) > 0; }
double GlobalVariableGet(const string& n) { return W.gv.count(n) ? W.gv[n] : 0.0; }
string GlobalVariableName(int i) { int k = 0; for(auto& kv : W.gv) if(k++ == i) return kv.first; return ""; }
datetime GlobalVariableSet(const string& n, double v) { W.gv[n] = v; W.gv_time[n] = W.now; return W.now; }
bool GlobalVariableSetOnCondition(const string& n, double v, double chk) {
  if(!W.gv.count(n) || W.gv[n] != chk) return false; W.gv[n] = v; W.gv_time[n] = W.now; return true; }
bool GlobalVariableTemp(const string& n) { if(!W.gv.count(n)) { W.gv[n] = 0.0; W.gv_time[n] = W.now; } return true; }
datetime GlobalVariableTime(const string& n) { return W.gv_time.count(n) ? W.gv_time[n] : 0; }
void GlobalVariablesFlush() {}
int GlobalVariablesTotal() { return (int)W.gv.size(); }
bool HistorySelect(datetime, datetime) { W.sel_deals.clear(); for(auto& d : W.deals) W.sel_deals.push_back(d.ticket); return true; }
bool HistorySelectByPosition(long pid) { W.sel_deals.clear(); for(auto& d : W.deals) if(d.pos_id == pid) W.sel_deals.push_back(d.ticket); return true; }
int HistoryDealsTotal() { return (int)W.sel_deals.size(); }
ulong HistoryDealGetTicket(int i) { return (i >= 0 && i < (int)W.sel_deals.size()) ? W.sel_deals[i] : 0; }
long HistoryDealGetInteger(ulong t, ENUM_DEAL_PROPERTY_INTEGER p) {
  MockDeal* d = mock_deal(t); if(!d) return 0;
  switch(p) { case DEAL_ENTRY: return d->entry; case DEAL_MAGIC: return d->magic; case DEAL_ORDER: return (long)d->order;
              case DEAL_REASON: return d->reason; case DEAL_TIME: return d->time; case DEAL_TYPE: return d->type; case DEAL_POSITION_ID: return d->pos_id; }
  return 0;
}
double HistoryDealGetDouble(ulong t, ENUM_DEAL_PROPERTY_DOUBLE p) {
  MockDeal* d = mock_deal(t); if(!d) return 0;
  switch(p) { case DEAL_COMMISSION: return d->comm; case DEAL_PRICE: return d->price; case DEAL_PROFIT: return d->profit;
              case DEAL_SWAP: return d->swap; case DEAL_VOLUME: return d->vol; }
  return 0;
}
string HistoryDealGetString(ulong t, ENUM_DEAL_PROPERTY_STRING p) { MockDeal* d = mock_deal(t); if(!d) return ""; return p == DEAL_COMMENT ? d->cmt : d->sym; }
bool HistoryOrderSelect(ulong t) { return !W.hist_lag && mock_hist_order(t) != nullptr; }
long HistoryOrderGetInteger(ulong t, ENUM_ORDER_PROPERTY_INTEGER p) {
  MockOrder* o = W.hist_lag ? nullptr : mock_hist_order(t); if(!o) return 0;
  switch(p) { case ORDER_MAGIC: return o->magic; case ORDER_POSITION_ID: return o->pos_id; case ORDER_STATE: return o->state; case ORDER_TYPE: return o->type; }
  return 0;
}
double HistoryOrderGetDouble(ulong t, ENUM_ORDER_PROPERTY_DOUBLE p) {
  MockOrder* o = W.hist_lag ? nullptr : mock_hist_order(t); if(!o) return 0;
  switch(p) { case ORDER_PRICE_OPEN: return o->price; case ORDER_SL: return o->sl; case ORDER_VOLUME_CURRENT: return o->vc; case ORDER_VOLUME_INITIAL: return o->vi; }
  return 0;
}
string HistoryOrderGetString(ulong t, ENUM_ORDER_PROPERTY_STRING p) { MockOrder* o = W.hist_lag ? nullptr : mock_hist_order(t); if(!o) return "";
                                                                      return p == ORDER_COMMENT ? o->cmt : o->sym; }
int OrdersTotal() { return (int)W.orders.size(); }
ulong OrderGetTicket(int i) { if(i < 0 || i >= (int)W.orders.size()) return 0; W.sel_order = i; return W.orders[i].ticket; }
bool OrderSelect(ulong t) { for(int i = 0; i < (int)W.orders.size(); i++) if(W.orders[i].ticket == t) { W.sel_order = i; return true; } return false; }
static MockOrder* mock_sel_order() { return (W.sel_order >= 0 && W.sel_order < (int)W.orders.size()) ? &W.orders[W.sel_order] : nullptr; }
long OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER p) {
  MockOrder* o = mock_sel_order(); if(!o) return 0;
  switch(p) { case ORDER_MAGIC: return o->magic; case ORDER_POSITION_ID: return o->pos_id; case ORDER_STATE: return o->state; case ORDER_TYPE: return o->type; }
  return 0;
}
double OrderGetDouble(ENUM_ORDER_PROPERTY_DOUBLE p) {
  MockOrder* o = mock_sel_order(); if(!o) return 0;
  switch(p) { case ORDER_PRICE_OPEN: return o->price; case ORDER_SL: return o->sl; case ORDER_VOLUME_CURRENT: return o->vc; case ORDER_VOLUME_INITIAL: return o->vi; }
  return 0;
}
string OrderGetString(ENUM_ORDER_PROPERTY_STRING p) { MockOrder* o = mock_sel_order(); if(!o) return ""; return p == ORDER_COMMENT ? o->cmt : o->sym; }
bool OrderCalcMargin(ENUM_ORDER_TYPE, const string&, double vol, double, double& m) { m = vol * 1000.0; return true; }
int PositionsTotal() { return (int)W.positions.size(); }
ulong PositionGetTicket(int i) { if(i < 0 || i >= (int)W.positions.size()) return 0; W.sel_pos = i; return W.positions[i].ticket; }
bool PositionSelectByTicket(ulong t) { for(int i = 0; i < (int)W.positions.size(); i++) if(W.positions[i].ticket == t) { W.sel_pos = i; return true; } return false; }
static MockPos* mock_sel_pos() { return (W.sel_pos >= 0 && W.sel_pos < (int)W.positions.size()) ? &W.positions[W.sel_pos] : nullptr; }
long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER p) {
  MockPos* q = mock_sel_pos(); if(!q) return 0;
  switch(p) { case POSITION_IDENTIFIER: return q->id; case POSITION_MAGIC: return q->magic; case POSITION_TIME: return q->time; case POSITION_TYPE: return q->type; }
  return 0;
}
double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE p) {
  MockPos* q = mock_sel_pos(); if(!q) return 0;
  switch(p) { case POSITION_PRICE_OPEN: return q->price; case POSITION_SL: return q->sl; case POSITION_VOLUME: return q->vol; }
  return 0;
}
string PositionGetString(ENUM_POSITION_PROPERTY_STRING p) { MockPos* q = mock_sel_pos(); if(!q) return ""; return p == POSITION_COMMENT ? q->cmt : q->sym; }
bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double) { return true; }
bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double, datetime, double) { return true; }
bool ObjectDelete(long, const string&) { return true; }
int ObjectFind(long, const string&) { return -1; }
bool ObjectSetInteger(long, const string&, ENUM_OBJECT_PROPERTY_INTEGER, long) { return true; }
bool ObjectSetString(long, const string&, ENUM_OBJECT_PROPERTY_STRING, const string&) { return true; }
int ObjectsDeleteAll(long, const string&, int = -1, int = -1) { return 0; }
bool TextSetFont(const string&, int, uint, int = 0) { return true; }
bool TextGetSize(const string&, uint&, uint&) { return true; }

//--- 建玉を閉じる（決済の約定を履歴に足す）
inline void mock_close_position(ulong t, double price, long reason) {
  for(size_t i = 0; i < W.positions.size(); i++)
    if(W.positions[i].ticket == t) {
      MockPos q = W.positions[i];
      W.positions.erase(W.positions.begin() + (long)i);
      double profit = (price - q.price) * (q.type == POSITION_TYPE_BUY ? 1 : -1) * q.vol * 100000.0;
      mock_add_deal(0, q.id, q.sym, q.magic, DEAL_ENTRY_OUT, q.type == POSITION_TYPE_BUY ? DEAL_TYPE_SELL : DEAL_TYPE_BUY, reason, price, q.vol, profit, "");
      return;
    }
}

class CTrade {
public:
  ulong magic = 0;
  uint rc = 0;
  ulong order = 0;
  void SetExpertMagicNumber(const ulong m) { magic = m; }
  void SetDeviationInPoints(const ulong) {}
  bool SetTypeFillingBySymbol(const string&) { return true; }
  void SetTypeFilling(const ENUM_ORDER_TYPE_FILLING) {}
  bool Market(int dir, double vol, const string& sym, double sl, const string& cmt) {
    W.n_market++;
    if(W.fail_send) { rc = W.fail_send; return false; }
    ulong t = W.next_ticket++;
    order = t;
    double px = dir == 1 ? W.ask : W.bid;
    if(W.market_reject) {                // 受け付けた後に拒否された
      rc = TRADE_RETCODE_PLACED;
      W.hist_orders.push_back(MockOrder{t, sym, (long)magic, dir == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, ORDER_STATE_REJECTED, vol, vol, px, sl, cmt, 0});
      return true;
    }
    rc = TRADE_RETCODE_DONE;
    W.positions.push_back(MockPos{t, (long)t, sym, (long)magic, dir == 1 ? POSITION_TYPE_BUY : POSITION_TYPE_SELL, vol, px, sl, W.now, cmt});
    W.hist_orders.push_back(MockOrder{t, sym, (long)magic, dir == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, ORDER_STATE_FILLED, vol, 0.0, px, sl, cmt, (long)t});
    mock_add_deal(t, (long)t, sym, (long)magic, DEAL_ENTRY_IN, dir == 1 ? DEAL_TYPE_BUY : DEAL_TYPE_SELL, DEAL_REASON_EXPERT, px, vol, 0.0, cmt);
    return true;
  }
  bool Buy(const double v, const string& s = "", double = 0.0, const double sl = 0.0, const double = 0.0, const string& cmt = "") { return Market(1, v, s, sl, cmt); }
  bool Sell(const double v, const string& s = "", double = 0.0, const double sl = 0.0, const double = 0.0, const string& cmt = "") { return Market(-1, v, s, sl, cmt); }
  bool Pending(long type, double vol, double price, const string& sym, double sl, const string& cmt) {
    if(W.fail_send) { rc = W.fail_send; return false; }
    ulong t = W.next_ticket++;
    order = t;
    rc = TRADE_RETCODE_DONE;
    W.orders.push_back(MockOrder{t, sym, (long)magic, type, ORDER_STATE_PLACED, vol, vol, price, sl, cmt, 0});
    return true;
  }
  bool BuyStop(const double v, const double p, const string& s = "", const double sl = 0.0, const double = 0.0,
               const ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, const datetime = 0, const string& cmt = "") { W.n_buystop++; return Pending(ORDER_TYPE_BUY_STOP, v, p, s, sl, cmt); }
  bool SellStop(const double v, const double p, const string& s = "", const double sl = 0.0, const double = 0.0,
                const ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, const datetime = 0, const string& cmt = "") { W.n_sellstop++; return Pending(ORDER_TYPE_SELL_STOP, v, p, s, sl, cmt); }
  bool OrderModify(const ulong t, const double p, const double sl, const double, const ENUM_ORDER_TYPE_TIME, const datetime, const double = 0.0) {
    W.n_modify++;
    if(W.fail_modify) { rc = W.fail_modify; return false; }
    MockOrder* o = mock_order(t); if(!o) { rc = 10013; return false; }
    o->price = p; o->sl = sl; rc = TRADE_RETCODE_DONE; return true;
  }
  bool OrderDelete(const ulong t) {
    W.n_delete++;
    if(W.fail_delete) { rc = W.fail_delete; return false; }
    for(size_t i = 0; i < W.orders.size(); i++)
      if(W.orders[i].ticket == t) {
        MockOrder o = W.orders[i]; o.state = ORDER_STATE_CANCELED;
        W.orders.erase(W.orders.begin() + (long)i); W.hist_orders.push_back(o); rc = TRADE_RETCODE_DONE; return true;
      }
    rc = 10013; return false;
  }
  bool PositionClose(const ulong t, const ulong = ULONG_MAX) {
    W.n_close++;
    MockPos* q = mock_pos(t);
    if(q && W.close_gone) { mock_close_position(t, q->sl, DEAL_REASON_SL); rc = 10036; return false; }   // その直前に SL で閉じていた
    if(W.fail_close) { rc = W.fail_close; return false; }
    if(!q) { rc = 10036; return false; }
    mock_close_position(t, q->type == POSITION_TYPE_BUY ? W.bid : W.ask, DEAL_REASON_EXPERT);
    rc = TRADE_RETCODE_DONE; return true;
  }
  bool PositionModify(const ulong t, const double sl, const double) {
    if(W.fail_posmod) { rc = W.fail_posmod; return false; }
    MockPos* q = mock_pos(t); if(!q) { rc = 10036; return false; }
    q->sl = sl; rc = TRADE_RETCODE_DONE; return true;
  }
  uint ResultRetcode() const { return rc; }
  string ResultRetcodeDescription() const { return "mock"; }
  ulong ResultOrder() const { return order; }
};
