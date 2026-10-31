// 接続部の C++ 構文・型チェック用の MQL5 API の代用（動作はしない。宣言と型だけ）
#pragma once
#include <climits>
#include <cstdarg>

// MqlArray<bool>（std::vector<bool> の参照の代わり）
template<> struct MqlArray<bool> {
  std::vector<unsigned char> v;
  bool& operator[](int i) { return reinterpret_cast<bool&>(v[i]); }
  const bool& operator[](int i) const { return reinterpret_cast<const bool&>(v[i]); }
};
template<class T> bool ArraySetAsSeries(MqlArray<T>& a, bool f) { (void)a; (void)f; return true; }
template<class T> int ArrayResize(MqlArray<T>& a, int n, int reserve, int) { (void)reserve; a.v.resize(n); return n; }

#define INIT_SUCCEEDED 0
#define INIT_FAILED 1
#define INIT_PARAMETERS_INCORRECT 32767
#define INVALID_HANDLE (-1)
#define CP_ACP 0
#define CP_UTF8 65001
#define FILE_READ 1
#define FILE_WRITE 2
#define FILE_TXT 16
#define FILE_ANSI 32
#define FILE_SHARE_READ 128
#define FILE_SHARE_WRITE 256
#define FILE_REWRITE 512
#define FILE_COMMON 4096
#define REASON_PROGRAM 0
#define REASON_REMOVE 1
#define REASON_RECOMPILE 2
#define REASON_CHARTCHANGE 3
#define REASON_CHARTCLOSE 4
#define REASON_PARAMETERS 5
#define REASON_ACCOUNT 6
#define REASON_TEMPLATE 7
#define REASON_INITFAILED 8
#define REASON_CLOSE 9
#define SYMBOL_EXPIRATION_GTC 1
#define SYMBOL_EXPIRATION_DAY 2

enum ENUM_TIMEFRAMES { PERIOD_CURRENT = 0, PERIOD_M1 = 1, PERIOD_H1 = 16385 };
enum ENUM_ACCOUNT_INFO_INTEGER { ACCOUNT_LOGIN, ACCOUNT_TRADE_ALLOWED, ACCOUNT_TRADE_EXPERT };
enum ENUM_ACCOUNT_INFO_DOUBLE { ACCOUNT_BALANCE, ACCOUNT_MARGIN_FREE };
enum ENUM_MQL_INFO_INTEGER { MQL_TESTER, MQL_OPTIMIZATION, MQL_VISUAL_MODE, MQL_TRADE_ALLOWED };
enum ENUM_TERMINAL_INFO_INTEGER { TERMINAL_CONNECTED, TERMINAL_MAXBARS, TERMINAL_NOTIFICATIONS_ENABLED, TERMINAL_TRADE_ALLOWED };
enum ENUM_SERIES_INFO_INTEGER { SERIES_SYNCHRONIZED, SERIES_SERVER_FIRSTDATE, SERIES_FIRSTDATE, SERIES_TERMINAL_FIRSTDATE };
enum ENUM_SYMBOL_INFO_INTEGER { SYMBOL_DIGITS, SYMBOL_EXPIRATION_MODE, SYMBOL_TRADE_FREEZE_LEVEL, SYMBOL_TRADE_MODE, SYMBOL_TRADE_STOPS_LEVEL };
enum ENUM_SYMBOL_INFO_DOUBLE { SYMBOL_ASK, SYMBOL_BID, SYMBOL_POINT, SYMBOL_TRADE_TICK_SIZE, SYMBOL_TRADE_TICK_VALUE, SYMBOL_VOLUME_MAX, SYMBOL_VOLUME_MIN, SYMBOL_VOLUME_STEP };
enum ENUM_SYMBOL_TRADE_MODE { SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_LONGONLY, SYMBOL_TRADE_MODE_SHORTONLY, SYMBOL_TRADE_MODE_CLOSEONLY, SYMBOL_TRADE_MODE_FULL };
enum ENUM_CHART_PROPERTY_INTEGER { CHART_SHOW_ONE_CLICK, CHART_HEIGHT_IN_PIXELS };
enum ENUM_POINTER_TYPE { POINTER_INVALID, POINTER_DYNAMIC, POINTER_AUTOMATIC };
enum ENUM_FILE_POSITION { SEEK_SET_, SEEK_CUR_, SEEK_END_ };
#undef SEEK_END
#define SEEK_END SEEK_END_
enum ENUM_DEAL_PROPERTY_INTEGER { DEAL_ENTRY, DEAL_MAGIC, DEAL_ORDER, DEAL_REASON, DEAL_TIME, DEAL_TYPE, DEAL_POSITION_ID };
enum ENUM_DEAL_PROPERTY_DOUBLE { DEAL_COMMISSION, DEAL_PRICE, DEAL_PROFIT, DEAL_SWAP, DEAL_VOLUME };
enum ENUM_DEAL_PROPERTY_STRING { DEAL_COMMENT, DEAL_SYMBOL };
enum ENUM_DEAL_ENTRY { DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY };
enum ENUM_DEAL_TYPE { DEAL_TYPE_BUY, DEAL_TYPE_SELL };
enum ENUM_DEAL_REASON { DEAL_REASON_CLIENT, DEAL_REASON_MOBILE, DEAL_REASON_WEB, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP, DEAL_REASON_SO };
enum ENUM_ORDER_PROPERTY_INTEGER { ORDER_MAGIC, ORDER_POSITION_ID, ORDER_STATE, ORDER_TYPE };
enum ENUM_ORDER_PROPERTY_DOUBLE { ORDER_PRICE_OPEN, ORDER_SL, ORDER_VOLUME_CURRENT, ORDER_VOLUME_INITIAL };
enum ENUM_ORDER_PROPERTY_STRING { ORDER_COMMENT, ORDER_SYMBOL };
enum ENUM_ORDER_STATE { ORDER_STATE_STARTED, ORDER_STATE_PLACED, ORDER_STATE_CANCELED, ORDER_STATE_PARTIAL, ORDER_STATE_FILLED, ORDER_STATE_REJECTED, ORDER_STATE_EXPIRED };
enum ENUM_ORDER_TYPE { ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT, ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP, ORDER_TYPE_BUY_STOP_LIMIT, ORDER_TYPE_SELL_STOP_LIMIT };
enum ENUM_ORDER_TYPE_TIME { ORDER_TIME_GTC, ORDER_TIME_DAY };
enum ENUM_ORDER_TYPE_FILLING { ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN };
enum ENUM_POSITION_PROPERTY_INTEGER { POSITION_IDENTIFIER, POSITION_MAGIC, POSITION_TIME, POSITION_TYPE };
enum ENUM_POSITION_PROPERTY_DOUBLE { POSITION_PRICE_OPEN, POSITION_SL, POSITION_VOLUME };
enum ENUM_POSITION_PROPERTY_STRING { POSITION_COMMENT, POSITION_SYMBOL };
enum ENUM_POSITION_TYPE { POSITION_TYPE_BUY, POSITION_TYPE_SELL };
enum ENUM_OBJECT { OBJ_ARROW, OBJ_HLINE, OBJ_LABEL, OBJ_RECTANGLE_LABEL, OBJ_TREND };
enum ENUM_OBJECT_PROPERTY_INTEGER { OBJPROP_ANCHOR, OBJPROP_ARROWCODE, OBJPROP_BACK, OBJPROP_BGCOLOR, OBJPROP_BORDER_TYPE, OBJPROP_COLOR, OBJPROP_CORNER,
  OBJPROP_FONTSIZE, OBJPROP_HIDDEN, OBJPROP_RAY_RIGHT, OBJPROP_SELECTABLE, OBJPROP_STYLE, OBJPROP_WIDTH, OBJPROP_XDISTANCE, OBJPROP_XSIZE,
  OBJPROP_YDISTANCE, OBJPROP_YSIZE };
enum ENUM_OBJECT_PROPERTY_STRING { OBJPROP_FONT, OBJPROP_TEXT };
enum ENUM_ARROW_ANCHOR { ANCHOR_TOP, ANCHOR_BOTTOM };
enum ENUM_ANCHOR_POINT { ANCHOR_LEFT_UPPER = 10 };
enum ENUM_BASE_CORNER { CORNER_LEFT_UPPER };
enum ENUM_BORDER_TYPE { BORDER_FLAT };
enum ENUM_LINE_STYLE { STYLE_SOLID, STYLE_DASH, STYLE_DOT };
enum ENUM_TRADE_RETCODE { TRADE_RETCODE_REQUOTE = 10004, TRADE_RETCODE_REJECT = 10006, TRADE_RETCODE_PLACED = 10008, TRADE_RETCODE_DONE = 10009,
  TRADE_RETCODE_DONE_PARTIAL = 10010, TRADE_RETCODE_ERROR = 10011, TRADE_RETCODE_TIMEOUT = 10012, TRADE_RETCODE_INVALID_PRICE = 10015,
  TRADE_RETCODE_INVALID_STOPS = 10016, TRADE_RETCODE_TRADE_DISABLED = 10017, TRADE_RETCODE_MARKET_CLOSED = 10018, TRADE_RETCODE_NO_MONEY = 10019,
  TRADE_RETCODE_PRICE_CHANGED = 10020, TRADE_RETCODE_PRICE_OFF = 10021, TRADE_RETCODE_TOO_MANY_REQUESTS = 10024, TRADE_RETCODE_NO_CHANGES = 10025,
  TRADE_RETCODE_LOCKED = 10028, TRADE_RETCODE_FROZEN = 10029, TRADE_RETCODE_INVALID_FILL = 10030, TRADE_RETCODE_CONNECTION = 10031 };

const color clrSilver = 1, clrDeepSkyBlue = 2, clrLime = 3, clrOrange = 4, clrYellow = 5, clrKhaki = 6, clrGold = 7, clrTomato = 8, clrGray = 9,
  clrWhite = 10, clrLightCyan = 11, clrRed = 12, clrDodgerBlue = 13, clrIndianRed = 14, clrSteelBlue = 15;

struct MqlTick { datetime time; double bid; double ask; double last; ulong volume; long time_msc; uint flags; double volume_real; };

static string _Symbol = "EURUSD";

// 構文・型の確認（conncheck.py）は下の「動かない代用」を使う。接続部のシナリオ試験（conntest.cpp）は CONN_MOCK を定義して、
// 注文・建玉・約定履歴・グローバル変数・ファイル・時計を持つ模擬（conn_mock.h）を使う
#ifdef CONN_MOCK
#include "conn_mock.h"
#else
long AccountInfoInteger(ENUM_ACCOUNT_INFO_INTEGER) { return 0; }
double AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE) { return 0; }
int MQLInfoInteger(ENUM_MQL_INFO_INTEGER) { return 0; }
int TerminalInfoInteger(ENUM_TERMINAL_INFO_INTEGER) { return 0; }
long SeriesInfoInteger(const string&, ENUM_TIMEFRAMES, ENUM_SERIES_INFO_INTEGER) { return 0; }
long SymbolInfoInteger(const string&, ENUM_SYMBOL_INFO_INTEGER) { return 0; }
double SymbolInfoDouble(const string&, ENUM_SYMBOL_INFO_DOUBLE) { return 0; }
bool SymbolInfoTick(const string&, MqlTick&) { return true; }
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
uint GetTickCount() { return 0; }
datetime TimeCurrent() { return 0; }
datetime TimeGMT() { return 0; }
datetime TimeLocal() { return 0; }
datetime TimeTradeServer() { return 0; }
inline double MathRound(double v) { return std::floor(v + 0.5); }
inline double MathPow(double b, double e) { return std::pow(b, e); }
inline double NormalizeDouble(double v, int) { return v; }
inline string ShortToString(ushort ch) { return string(1, (char)ch); }
inline int StringCompare(const string& a, const string& b, bool = true) { return a.compare(b); }
template<class... A> void Print(A... a) { (void)sizeof...(a); }
template<class... A> void Alert(A... a) { (void)sizeof...(a); }
template<class... A> void PrintFormat(const string& f, A... a) { (void)f; (void)sizeof...(a); }
bool SendNotification(const string&) { return true; }
int FileOpen(const string&, int, short = '\t', uint = CP_ACP) { return 0; }
void FileClose(int) {}
void FileFlush(int) {}
uint FileWriteString(int, const string&, int = -1) { return 0; }
ulong FileSize(int) { return 0; }
bool FileSeek(int, long, ENUM_FILE_POSITION) { return true; }
bool FileIsExist(const string&, int = 0) { return false; }
bool FileDelete(const string&, int = 0) { return true; }
bool FileMove(const string&, int, const string&, int) { return true; }
long FileFindFirst(const string&, string&, int = 0) { return -1; }
bool FileFindNext(long, string&) { return false; }
void FileFindClose(long) {}
bool FolderCreate(const string&, int = 0) { return true; }
bool FolderClean(const string&, int = 0) { return true; }
bool FolderDelete(const string&, int = 0) { return true; }
bool GlobalVariableCheck(const string&) { return false; }
bool GlobalVariableDel(const string&) { return true; }
double GlobalVariableGet(const string&) { return 0; }
string GlobalVariableName(int) { return ""; }
datetime GlobalVariableSet(const string&, double) { return 0; }
bool GlobalVariableSetOnCondition(const string&, double, double) { return true; }
bool GlobalVariableTemp(const string&) { return true; }
datetime GlobalVariableTime(const string&) { return 0; }
void GlobalVariablesFlush() {}
int GlobalVariablesTotal() { return 0; }
bool HistorySelect(datetime, datetime) { return true; }
bool HistorySelectByPosition(long) { return true; }
int HistoryDealsTotal() { return 0; }
ulong HistoryDealGetTicket(int) { return 0; }
long HistoryDealGetInteger(ulong, ENUM_DEAL_PROPERTY_INTEGER) { return 0; }
double HistoryDealGetDouble(ulong, ENUM_DEAL_PROPERTY_DOUBLE) { return 0; }
string HistoryDealGetString(ulong, ENUM_DEAL_PROPERTY_STRING) { return ""; }
bool HistoryOrderSelect(ulong) { return true; }
long HistoryOrderGetInteger(ulong, ENUM_ORDER_PROPERTY_INTEGER) { return 0; }
double HistoryOrderGetDouble(ulong, ENUM_ORDER_PROPERTY_DOUBLE) { return 0; }
string HistoryOrderGetString(ulong, ENUM_ORDER_PROPERTY_STRING) { return ""; }
int OrdersTotal() { return 0; }
ulong OrderGetTicket(int) { return 0; }
bool OrderSelect(ulong) { return true; }
long OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER) { return 0; }
double OrderGetDouble(ENUM_ORDER_PROPERTY_DOUBLE) { return 0; }
string OrderGetString(ENUM_ORDER_PROPERTY_STRING) { return ""; }
bool OrderCalcMargin(ENUM_ORDER_TYPE, const string&, double, double, double&) { return true; }
int PositionsTotal() { return 0; }
ulong PositionGetTicket(int) { return 0; }
bool PositionSelectByTicket(ulong) { return true; }
long PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER) { return 0; }
double PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE) { return 0; }
string PositionGetString(ENUM_POSITION_PROPERTY_STRING) { return ""; }
bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double) { return true; }
bool ObjectCreate(long, const string&, ENUM_OBJECT, int, datetime, double, datetime, double) { return true; }
bool ObjectDelete(long, const string&) { return true; }
int ObjectFind(long, const string&) { return -1; }
bool ObjectSetInteger(long, const string&, ENUM_OBJECT_PROPERTY_INTEGER, long) { return true; }
bool ObjectSetString(long, const string&, ENUM_OBJECT_PROPERTY_STRING, const string&) { return true; }
int ObjectsDeleteAll(long, const string&, int = -1, int = -1) { return 0; }
bool TextSetFont(const string&, int, uint, int = 0) { return true; }   // flags に既定値はない（MQL5 リファレンス）
bool TextGetSize(const string&, uint&, uint&) { return true; }

class CTrade {
public:
  void SetExpertMagicNumber(const ulong) {}
  void SetDeviationInPoints(const ulong) {}
  bool SetTypeFillingBySymbol(const string&) { return true; }
  void SetTypeFilling(const ENUM_ORDER_TYPE_FILLING) {}
  bool Buy(const double, const string& = "", double = 0.0, const double = 0.0, const double = 0.0, const string& = "") { return true; }
  bool Sell(const double, const string& = "", double = 0.0, const double = 0.0, const double = 0.0, const string& = "") { return true; }
  bool BuyStop(const double, const double, const string& = "", const double = 0.0, const double = 0.0,
               const ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, const datetime = 0, const string& = "") { return true; }
  bool SellStop(const double, const double, const string& = "", const double = 0.0, const double = 0.0,
                const ENUM_ORDER_TYPE_TIME = ORDER_TIME_GTC, const datetime = 0, const string& = "") { return true; }
  bool OrderModify(const ulong, const double, const double, const double, const ENUM_ORDER_TYPE_TIME, const datetime, const double = 0.0) { return true; }
  bool OrderDelete(const ulong) { return true; }
  bool PositionClose(const ulong, const ulong = ULONG_MAX) { return true; }
  bool PositionModify(const ulong, const double, const double) { return true; }
  uint ResultRetcode() const { return 0; }
  string ResultRetcodeDescription() const { return ""; }
  ulong ResultOrder() const { return 0; }
};
#endif
