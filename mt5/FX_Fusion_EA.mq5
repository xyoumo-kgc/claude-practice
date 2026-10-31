//+------------------------------------------------------------------+
//|  FX_Fusion_EA.mq5                                                |
//|  融合FXシステム FUSION-CORE v1.0                                  |
//|  「賢人のデイトレード × 100億円トレーダー」                        |
//|                                                                  |
//|  仕様: fusion/SPEC.md（凍結）  参照実装: fusion/strategy.py        |
//|  約定モデル: fusion/broker.py  スイング: fusion/indicators.py      |
//|                                                                  |
//|  【一言で】(SPEC §0.1)                                            |
//|   4H レベルの上昇（下降）構造の中で、押し（戻り）が 4H MA（1H 足の |
//|   SMA80）に届き、その 4H MA が逆向きでないときに、1H レベルで     |
//|   「安値切上げを保ったまま戻り高値を上抜ける」瞬間を逆指値で取る。 |
//|   損切りは切上げ安値の外。出口は「4H の新しい押し安値が確定する   |
//|   たびに損切りを引き上げる」と「週末・休場の前に全決済」だけ。     |
//|   分割・建値移動・固定利確・時間決済はしない。                     |
//|                                                                  |
//|  【優位性の状態】                                                 |
//|   検証中（結果は fusion/RESULTS.md）。設計時の開発期間の成績は、   |
//|   約190構成の探索による選択バイアスを含む。前身 MinCore の審査     |
//|   ホールドアウトは 2010〜2012 が PF1.06、AUDUSD・USDCAD 2013〜2017 |
//|   が PF0.76。従来版EA・4P-Score も実データの検証期間ではマイナス。 |
//|   自動売買は既定 OFF。§21 の検証に合格し、デモでのフォワード3か月 |
//|   を終えるまでは、シグナル通知とパネルだけで使う。                 |
//|                                                                  |
//|  【使い方】                                                       |
//|   ・どの時間足のチャートに付けてもよい。判定は常に H1 の確定足。   |
//|   ・監視銘柄は InpSymbols（カンマ区切り。空ならチャートの銘柄）。  |
//|     EURUSD.a・XAUUSDm などの接尾辞つきでよい。名目スプレッド s_nom |
//|     は銘柄名の先頭6文字で SPEC §10.3 の表から引く（GOLD〜 は       |
//|     XAUUSD 扱い。表にない銘柄は InpSpreadPointsDefault ポイント）。|
//|   ・初回に H1 の確定足を InpHistoryBars 本（既定10000。D1 帳簿が   |
//|     8000本を使うので 8100 以上）読み込み、Python と同じループを    |
//|     先頭から「仮想」で再生して、約定済み集合・待機注文・建玉を復元 |
//|     する（この間は通知しない）。その後は新しい確定足を末尾に追記し、|
//|     毎時、直近の確定足を CopyRates で取り直して手元と照合する       |
//|     （食い違えば読み込み直して再生する）。                         |
//|   ・新しい H1 足は OnTimer（InpTimerSeconds 秒ごと）で全銘柄を巡回 |
//|     して検出する（OnTick はチャートの銘柄でしか来ないため）。       |
//|                                                                  |
//|  【処理順】fusion/strategy.py run_h1 のループと同じ               |
//|   1) 休場明けフォールバック（足の始まりで判定。待機注文を取消し、  |
//|      建玉は始値で決済）                                            |
//|   2) 逆指値の約定判定（Ask 高値／Bid 安値。窓開けは始値で約定）    |
//|   3) 建玉の足処理（窓開け → SL 優先。約定足は SL だけ）            |
//|   4) 確定時の週末・休場決済と構造トレール                          |
//|   5) 新規停止・ロールオーバー（時刻ルール SPEC §2.6）              |
//|   6) 新規判定（買い→売り、スコアの高い方、同点は買い）と待機注文の |
//|      新規／置き直し／取消                                          |
//|                                                                  |
//|  【動作モード】                                                   |
//|   ・既定（InpAutoTrade=false）: シグナル通知＋パネル。建玉と約定は |
//|     fusion/broker.py と同じ仮想ブローカー（固定スプレッド s_nom、  |
//|     足の高安で判定、SL 優先、窓開け）で追う。通知（ARMED/FILLED/   |
//|     TRAIL/EXIT/INVALID）と Python の取引一覧が一致する。           |
//|   ・InpAutoTrade=true: 実際の BUY STOP/SELL STOP（SL つき、TP なし）|
//|     を置き、毎時 price・SL を修正し、取消・構造トレール・週末/休場 |
//|     決済・休場明けの成行決済を行う（SPEC §16.5・§17.5）。仮想      |
//|     ブローカーも並行して動かし、ログ（照合用）は仮想側を書く。     |
//|                                                                  |
//|  【ログ】MQL5/Files/FusionEA/（InpLogsCommon=true なら共通フォルダ）|
//|   起動・読み直しのたびに作り直す（再生分を含む）。ヘッダー行つき、 |
//|   カンマ区切り、時刻はサーバー時間 "YYYY.MM.DD HH:MM"。            |
//|   照合ハーネス fusion/mt5_parity.py がこの形式を読む。              |
//|                                                                  |
//|   <銘柄>_eval.csv … 足ごと・方向ごとの評価                        |
//|    bar_time  評価した確定足の開始時刻（Python の idx[t]）          |
//|    dir       1=買い / -1=売り / 0=時刻・建玉による見送り（T コード）|
//|    pattern   1=① / 3=③ / 0=T コード                               |
//|    key_time  key（買いは 1H 戻り高値 SH、売りは戻り安値）の足の時刻 |
//|              （R04 以降で出力。key=(dir, key_time)）              |
//|    code      R00〜R16 … SPEC §8 の最初の不成立（Python の funnel） |
//|              ARMED  … 新しい key で待機注文を置いた               |
//|                        （= Python の funnel['ARMED']）            |
//|              UPDATE … 同じ key の待機注文を置き直した             |
//|              LOSE   … 全条件を満たしたが、もう一方（スコアの高い  |
//|                        方。同点は買い）に負けた                    |
//|              T1〜T5 … 見送り（T1 休場日、T2 早仕舞い・週末前の新規|
//|                        停止、T3 ロールオーバー、T4 建玉あり、     |
//|                        T5 決済足）。ファネルには数えない           |
//|    price,sl,R  逆指値・損切り・R（価格単位。R09 以降で出力）      |
//|    r_atr     R/ATR                                                |
//|    depth,slope80,conv  押しの深さ・4H MA の傾き・MA 収束（R02 以降）|
//|    gap       4H MA と日足 MA の乖離（R12 以降。SMA480 未計算は空） |
//|    rel       日足との関係 T_D1×dir（R09 以降）                     |
//|    T_D1,T_BIG,T_SMALL  持続型ダウ状態（その足の確定時点。全行）    |
//|    n_sup,sup 背後の支えの数と種類（"FLIP+HZ+KEY" の形。R14 以降）  |
//|    rr_cf     反対勢力までの距離（R 単位。なしは 99。R15 以降）     |
//|    tp1       TP1 の目安（候補のとき）                             |
//|    S1〜S6,score  スコア内訳と合計（候補のとき）                    |
//|    phase     REPLAY（起動時の仮想再生）/ LIVE                     |
//|   数値は price 系が小数10桁、比率は小数6桁。未計算の欄は空。      |
//|                                                                  |
//|   <銘柄>_trades.csv … 仮想ブローカーの取引（fusion/broker.py と同じ）|
//|    entry_time  約定した足の開始時刻                                |
//|    dir, entry（スプレッド込みの約定価格）, initial_sl              |
//|    exit_time   SL/TRAIL/SL_gap/GAP_FALLBACK は足の開始時刻、       |
//|                WEEKEND/END は足の確定時刻（Python と同じ）         |
//|    exit_reason SL/TRAIL/SL_gap/WEEKEND/GAP_FALLBACK/END            |
//|    R（スプレッド込み）, bars_held, key_time, score, pattern,       |
//|    exit_price, mfe_r, mae_r, phase                                 |
//|    END は EA の停止時（OnDeinit）に、最後の確定足の終値で残りの    |
//|    仮想建玉を閉じた行（Python の run_h1 の最後と同じ計算）。       |
//|   <銘柄>_real.csv … 自動売買の実際の取引（InpAutoTrade=true のとき）|
//|   <銘柄>_bars.csv … 判定に使った H1 確定足（Time,Open,High,Low,Close。|
//|                     換算後の土日を除いた後。読込分＋以後の追記分）。  |
//|                     fusion/data.load_mt5_csv で読める。照合ではこの足を|
//|                     先頭から Python に渡すと、EA と同じ足番号になる。 |
//|   <銘柄>_info.csv … key,value: symbol, base, s_nom, is_xau,          |
//|                     server_offset_h, first_bar_time（最初に読み込んだ |
//|                     足）, first_eval_time（判定開始＝読込の93本目）,  |
//|                     bars_loaded, config, switches, params など        |
//|                                                                  |
//|  【Python との既知の差】                                          |
//|   ・EA の判定は「最初に読み込んだ足から Python を回した結果」と一致|
//|     する。Python を別の日から回すと、持続型ダウ状態機械（T_D1 など・|
//|     rel・S4・d1_gate）と待機注文・約定済み集合の初期状態が、最初の |
//|     転換イベントまでずれうる。移動平均は pandas と同じ Kahan 加算  |
//|     だが、始点が違うと最下位桁がずれうる（境界の判定 SPEC §17.6）。|
//|   ・InpHistoryBars が LB+N（D1 は 8072 本）より短いと、D1 帳簿と   |
//|     節目の候補が全履歴の Python と異なる。                          |
//|   ・自動売買の実約定はティック順・実スプレッドで決まるので、仮想   |
//|     ブローカー（ログ・パネルの累計）とずれうる（SPEC §17.11）。    |
//|     スプレッド防御・STOPS_LEVEL・FREEZE_LEVEL の見送りは実約定側だけ。|
//|   ・休場明けの決済は、Python は始値、実約定は最初のティックの成行。|
//|   ・InpServerOffsetHours は固定の時差なので、夏時間の切替がずれる  |
//|     週は時刻ルールが1時間ずれうる。換算後の土日の足は捨てる         |
//|     （オフセット0なら fusion/data.py の drop_weekend と同じ）。    |
//|                                                                  |
//|  【照合】判定エンジン部（//@@ENGINE_BEGIN〜END）は、MT5 の API を  |
//|   使わない。mt5/engine_check/run.sh がこの部分を C++ に写し、EA と |
//|   同じ流れ（読込→仮想再生→1本ずつ取り直し）で動かして、Python 参照 |
//|   実装と足ごと・方向ごとの理由コード、候補の値、取引一覧を突き合わ |
//|   せる（MetaEditor のない環境での確認用）。この部分を直したら回す。|
//+------------------------------------------------------------------+
#property copyright   "FUSION-CORE v1.0（賢人のデイトレード × 100億円トレーダー）"
#property version     "1.00"
#property description "4H の押し目・戻り目 × 1H の転換を H1 の確定足だけで判定（仕様 fusion/SPEC.md、参照実装 fusion/strategy.py）。"
#property description "既定はシグナル通知＋パネル。優位性は検証中（結果は fusion/RESULTS.md）。自動売買は既定 OFF。"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| 入力用の列挙型                                                    |
//+------------------------------------------------------------------+
enum ENUM_FUS_D1GATE
  {
   FUS_D1_OFF    = 0,   // off（既定。表示とスコアだけ）
   FUS_D1_STRICT = 1,   // strict（日足逆行なら見送り R11）
   FUS_D1_SOFT   = 2    // soft（日足逆行なら R の上限を半分に）
  };

enum ENUM_FUS_CFSCOPE
  {
   FUS_CF_STRONG = 0,   // strong（touch≥CF_MIN_TOUCH の節目。既定）
   FUS_CF_DAILY  = 1    // daily（日足級の節目）
  };

enum ENUM_FUS_SLMODE
  {
   FUS_SL_RUN  = 0,     // run（切上げ安値の外。既定）
   FUS_SL_NODE = 1      // node（近くの節目の外）
  };

//+------------------------------------------------------------------+
//| 入力パラメータ                                                    |
//+------------------------------------------------------------------+
input group "=== 監視 ==="
input string InpSymbols             = "";     // 監視銘柄（カンマ区切り。空ならチャートの銘柄）
input int    InpHistoryBars         = 10000;  // 初回に読み込む H1 確定足の本数（8100以上を推奨）
input int    InpTimerSeconds        = 5;      // 新しい H1 足を巡回する間隔（秒）
input int    InpServerOffsetHours   = 0;      // サーバー時間 −（NY+7）［時間］。時刻ルールの換算に使う
input double InpSpreadPointsDefault = 20;     // 表にない銘柄の名目スプレッド（ポイント）
input string InpExtraClosedDays     = "";     // 追加の休場日（YYYY.MM.DD をセミコロン区切り）
input string InpExtraEarlyDays      = "";     // 追加の早仕舞い日（YYYY.MM.DD をセミコロン区切り）

input group "=== 核心パラメータ（SPEC §12.1。理論値で固定） ==="
input int    InpN_BIG          = 12;    // N_BIG: 4H レベルのスイング深さ（H1 本数）
input int    InpN_SMALL        = 3;     // N_SMALL: 1H レベルのスイング深さ
input double InpZONE_ATR       = 0.5;   // ZONE_ATR: 押しが SMA80 に届いたとみなす帯（×ATR）
input double InpSLOPE_MIN      = 0.0;   // SLOPE_MIN: slope80·d の下限
input double InpENTRY_BUF_ATR  = 0.05;  // ENTRY_BUF_ATR: 逆指値を SH から離す幅（×ATR）
input double InpSL_BUF_ATR     = 0.2;   // SL_BUF_ATR: SL とトレールのバッファ（×ATR。下限 3×s_nom）
input double InpR_MIN_ATR      = 0.8;   // R_MIN_ATR: R の下限（×ATR）
input double InpR_MAX_ATR      = 3.0;   // R_MAX_ATR: R の上限（×ATR）

input group "=== 補助パラメータ（SPEC §12.2。表示・任意ゲート用） ==="
input int    InpN_D1           = 72;    // N_D1: 日足レベルのスイング深さ
input double InpTOL_LV         = 0.6;   // TOL_LV: 節目をまとめる幅（×ATR）
input double InpTOL_S          = 1.0;   // TOL_S: 背後の支えの許容幅（×ATR）
input int    InpCF_MIN_TOUCH   = 3;     // CF_MIN_TOUCH: 反対勢力とみなす節目の touch
input double InpRR_CF          = 2.0;   // RR_CF: clear_gate の閾値（R）
input double InpGAP_HI         = 8.0;   // GAP_HI: 乖離の上限（ATR_H1 単位）
input double InpLVL_MAX_ATR    = 3.0;   // LVL_MAX_ATR: g3 の上限（×ATR）

input group "=== 任意ゲート（既定は fusion 構成。変えると別の構成になる） ==="
input bool             InpG3          = false;          // g3: ブレイク水準が SMA80 から LVL_MAX_ATR 以内（R07）
input ENUM_FUS_D1GATE  InpD1Gate      = FUS_D1_OFF;     // d1_gate: 日足との関係
input bool             InpGapGate     = false;          // gap_gate: 乖離が大きく拡大中なら見送り（R12）
input bool             InpClearGate   = false;          // clear_gate: 反対勢力が RR_CF 未満なら見送り（R15）
input ENUM_FUS_CFSCOPE InpCfScope     = FUS_CF_STRONG;  // cf_scope: 反対勢力に数える節目
input bool             InpSupportGate = false;          // support_gate: 背後の支えなしなら見送り（R14）
input ENUM_FUS_SLMODE  InpSlMode      = FUS_SL_RUN;     // sl_mode: 損切りの基準
input bool             InpPattern3    = false;          // パターン③: 日足波の押し × 4H 終了兆候（既定 OFF）

input group "=== 通知・表示・ログ ==="
input bool   InpPushNotify     = true;         // スマホへプッシュ通知（SendNotification）
input bool   InpAlertPopup     = false;        // PC でアラートを出す
input bool   InpNotifyZone     = false;        // ZONE（トリガー待ち）も通知する
input bool   InpShowPanel      = true;         // パネルを表示する
input bool   InpDrawChart      = true;         // チャートの銘柄に SMA・スイング・節目・注文線を描く
input string InpPanelFont      = "MS Gothic";  // パネルのフォント
input int    InpPanelFontSize  = 9;            // パネルの文字の大きさ
input bool   InpWriteLogs      = true;         // 評価と取引の CSV を書く（MQL5/Files/FusionEA/）
input bool   InpLogsCommon     = false;        // CSV を共通フォルダ（Terminal/Common/Files）に書く

input group "=== 自動売買（既定 OFF。§21 の検証合格とデモ3か月の後に限る） ==="
input bool   InpAutoTrade       = false;     // 実際に逆指値を置いて売買する
input double InpRiskPercent     = 0.5;       // 1回のリスク（口座残高の%）
input long   InpMagicNumber     = 20261031;  // マジックナンバー
input int    InpDeviationPoints = 20;        // 成行の許容スリッページ（ポイント）

//@@ENGINE_BEGIN
//+------------------------------------------------------------------+
//| 判定エンジン（fusion/strategy.py の run_h1 を1銘柄ぶん移植）       |
//|                                                                  |
//|  ・ここから //@@ENGINE_END までは、発注・チャート・ファイルなどの  |
//|    MT5 API を使わない純粋な計算部。照合のため、同じソースを C++ に  |
//|    写して Python 参照実装と突き合わせている。                      |
//|  ・足は古い順。インデックスは最初に読み込んだ足からの通し番号で、  |
//|    Python を同じ足から回したときの足番号 t と一致する。            |
//|  ・初回の後は新しい確定足を末尾に追記する。移動平均は pandas の    |
//|    rolling().mean() と同じ Kahan 加算の増分計算、スイングは足      |
//|    j=t−N だけを判定して帳簿に足す増分方式（SPEC §4・§17.4）。      |
//|  ・帳簿の範囲は max(t−LB+2, N+1) ≤ j ≤ t−N（fusion/indicators.py）。|
//+------------------------------------------------------------------+
#define FE_NA        EMPTY_VALUE     // 未計算（Python の NaN に当たる）

//--- 理由コード（SPEC §8 の評価順）と評価ログの結果コード
#define RC_NONE     -1
#define RC_R00       0
#define RC_R01A      1
#define RC_R01       2
#define RC_R02       3
#define RC_R03       4
#define RC_R04       5
#define RC_R05       6
#define RC_R06       7
#define RC_R07       8
#define RC_R08       9
#define RC_R09      10
#define RC_R10      11
#define RC_R11      12
#define RC_R12      13
#define RC_R13      14
#define RC_R14      15
#define RC_R15      16
#define RC_R16      17
#define RC_OK       18    // 全条件を満たした候補
#define RC_ARMED    19    // 新しい key で待機注文を置いた
#define RC_UPDATE   20    // 同じ key の待機注文を置き直した
#define RC_LOSE     21    // 候補だが、もう一方にスコアで負けた
#define RC_T1       22    // 休場日
#define RC_T2       23    // 早仕舞い・週末前の新規停止
#define RC_T3       24    // ロールオーバー
#define RC_T4       25    // 建玉あり
#define RC_T5       26    // 決済足

//--- 決済理由（fusion/broker.py と同じ名前）
#define XR_SL        1
#define XR_TRAIL     2
#define XR_SLGAP     3
#define XR_WEEKEND   4
#define XR_GAP       5
#define XR_END       6

//--- イベント（通知・自動売買の材料）
#define EV_ARMED     1    // 新しい key の待機注文
#define EV_UPDATE    2    // 同じ key の置き直し
#define EV_INVALID   3    // 構造の崩れで取消（code=理由コード）
#define EV_CANCEL    4    // 時刻ルールによる取消（code=T コード）
#define EV_FILLED    5    // 約定
#define EV_TRAIL     6    // 損切りの引き上げ
#define EV_EXIT      7    // 決済（code=決済理由）
#define EV_GAP       8    // 休場明けフォールバック
#define EV_NONEW     9    // 新規停止の開始（code=1 なら待機注文を取消した）
#define EV_ZONE     10    // ZONE に入った（任意通知）

//--- 背後の支えの種類（ビット）
#define SUP_HZ       1
#define SUP_FLIP     2
#define SUP_KEY      4

//--- 判定パラメータ（SPEC §12）
struct SFusionParams
  {
   //--- 核心（§12.1）
   int               n_big;
   int               n_small;
   double            zone_atr;
   double            slope_min;
   double            entry_buf_atr;
   double            sl_buf_atr;
   double            r_min_atr;
   double            r_max_atr;
   //--- 補助（§12.2）
   int               n_d1;
   double            tol_lv;
   double            tol_s;
   int               cf_min_touch;
   double            rr_cf;
   double            gap_hi;
   double            lvl_max_atr;
   //--- 任意ゲート（§12.5。既定は fusion）
   bool              g3;
   int               d1_gate;        // 0=off 1=strict 2=soft
   bool              gap_gate;
   bool              clear_gate;
   int               cf_scope;       // 0=strong 1=daily
   bool              support_gate;
   int               sl_mode;        // 0=run 1=node
   bool              p3;
   //--- 固定定数（§12.4）
   int               slope_lb;
   int               lb_small;
   int               lb_big;
   int               lb_d1;
   int               l0_search;
   int               lv_win_big;
   int               lv_win_d1;
   double            spread_floor;
   double            conv_atr;
   double            tp1_min_r;
   double            tp_default_r;
   int               gap_fallback_h;
   //--- 銘柄・ブローカー
   double            s_nom;
   bool              is_xau;
   int               server_offset_h;
  };

//--- 移動平均の増分計算の状態（pandas rolling().mean() の roll_mean と同じ手順）
struct SRollMean
  {
   int               window;
   int               nobs;
   int               neg_ct;
   double            sum_x;
   double            comp_add;
   double            comp_rem;
   int               num_same;
   double            prev_value;
  };

//--- 節目（SPEC §6.2）
struct SLevel
  {
   double            price;
   int               touch;
   int               nh;
   int               nl;
   bool              d1;
  };

//--- 節目の候補点
struct SLvPoint
  {
   double            price;
   int               w;
   int               kind;
   bool              d1;
  };

//--- 1方向・1パターンの評価（Python の setup() の戻り値と meta）
//    stage: どこまで計算したか（1=depth 等、2=key、3=price/SL/R/rel、
//           4=gap、5=支え、6=rr_cf、7=全部）
struct SSetup
  {
   int               code;
   int               dir;
   int               pattern;
   int               stage;
   int               j_peak;
   int               key_idx;
   datetime          key_time;
   double            lvl;
   double            l0;
   double            run_ext;
   double            slope;
   double            depth;
   double            conv;
   double            atr;
   double            price;
   double            sl;
   double            R;
   double            r_atr;
   int               rel;
   double            gap;
   bool              gap_valid;
   bool              gap_bad;
   int               n_sup;
   int               sup_mask;
   double            th;
   double            rr_cf;
   double            near_r;
   double            tp1;
   double            tp2;
   bool              tp2_valid;
   int               s1;
   int               s2;
   int               s3;
   int               s4;
   int               s5;
   int               s6;
   int               score;
  };

//--- 仮想建玉（fusion/broker.py の Position。分割・建値なし）
struct SVPos
  {
   bool              active;
   int               dir;
   datetime          entry_time;
   int               entry_idx;
   double            entry;
   double            sl;
   double            init_sl;
   int               bars_held;
   double            mfe_r;
   double            mae_r;
   int               trails;
   SSetup            s;
  };

//--- 決済済みの取引（fusion/broker.py の trade_record）
struct STrade
  {
   datetime          entry_time;
   datetime          exit_time;
   datetime          key_time;
   int               dir;
   int               pattern;
   int               score;
   int               bars_held;
   int               reason;
   int               phase;
   double            entry;
   double            init_sl;
   double            exit_price;
   double            r;
   double            mfe_r;
   double            mae_r;
  };

//--- 通知・発注の材料
struct SFusionEvent
  {
   int               etype;
   int               dir;
   int               code;
   int               phase;
   int               trade_no;
   datetime          bar_time;
   double            price;
   double            sl;
   double            prev_price;
   double            prev_sl;
   double            value;
   SSetup            s;
  };

//--- 評価ログの1行
struct SEvalRow
  {
   datetime          bar_time;
   int               dir;
   int               pattern;
   int               code;
   int               phase;
   int               tD1;
   int               tBig;
   int               tSmall;
   int               endBig;
   SSetup            s;
  };

//+------------------------------------------------------------------+
//| 小道具                                                            |
//+------------------------------------------------------------------+
bool FE_IsNA(const double v)
  {
   return (v >= FE_NA);
  }

void FE_DefaultParams(SFusionParams &p)
  {
   p.n_big = 12;
   p.n_small = 3;
   p.zone_atr = 0.5;
   p.slope_min = 0.0;
   p.entry_buf_atr = 0.05;
   p.sl_buf_atr = 0.2;
   p.r_min_atr = 0.8;
   p.r_max_atr = 3.0;
   p.n_d1 = 72;
   p.tol_lv = 0.6;
   p.tol_s = 1.0;
   p.cf_min_touch = 3;
   p.rr_cf = 2.0;
   p.gap_hi = 8.0;
   p.lvl_max_atr = 3.0;
   p.g3 = false;
   p.d1_gate = 0;
   p.gap_gate = false;
   p.clear_gate = false;
   p.cf_scope = 0;
   p.support_gate = false;
   p.sl_mode = 0;
   p.p3 = false;
   p.slope_lb = 12;
   p.lb_small = 400;
   p.lb_big = 3000;
   p.lb_d1 = 8000;
   p.l0_search = 6;
   p.lv_win_big = 1200;
   p.lv_win_d1 = 2880;
   p.spread_floor = 3.0;
   p.conv_atr = 0.5;
   p.tp1_min_r = 1.0;
   p.tp_default_r = 2.0;
   p.gap_fallback_h = 12;
   p.s_nom = 0.0001;
   p.is_xau = false;
   p.server_offset_h = 0;
  }

void FE_SetupClear(SSetup &s)
  {
   s.code = RC_NONE;
   s.dir = 0;
   s.pattern = 0;
   s.stage = 0;
   s.j_peak = -1;
   s.key_idx = -1;
   s.key_time = 0;
   s.lvl = 0.0;
   s.l0 = 0.0;
   s.run_ext = 0.0;
   s.slope = 0.0;
   s.depth = 0.0;
   s.conv = 0.0;
   s.atr = 0.0;
   s.price = 0.0;
   s.sl = 0.0;
   s.R = 0.0;
   s.r_atr = 0.0;
   s.rel = 0;
   s.gap = 0.0;
   s.gap_valid = false;
   s.gap_bad = false;
   s.n_sup = 0;
   s.sup_mask = 0;
   s.th = 0.0;
   s.rr_cf = 99.0;
   s.near_r = 99.0;
   s.tp1 = 0.0;
   s.tp2 = 0.0;
   s.tp2_valid = false;
   s.s1 = 0;
   s.s2 = 0;
   s.s3 = 0;
   s.s4 = 0;
   s.s5 = 0;
   s.s6 = 0;
   s.score = 0;
  }

void FE_PosClear(SVPos &p)
  {
   p.active = false;
   p.dir = 0;
   p.entry_time = 0;
   p.entry_idx = -1;
   p.entry = 0.0;
   p.sl = 0.0;
   p.init_sl = 0.0;
   p.bars_held = 0;
   p.mfe_r = 0.0;
   p.mae_r = 0.0;
   p.trails = 0;
   FE_SetupClear(p.s);
  }

//+------------------------------------------------------------------+
//| 移動平均（pandas rolling(window).mean() と同じ Kahan 加算の増分）  |
//+------------------------------------------------------------------+
void FE_RollReset(SRollMean &r, const int window)
  {
   r.window = window;
   r.nobs = 0;
   r.neg_ct = 0;
   r.sum_x = 0.0;
   r.comp_add = 0.0;
   r.comp_rem = 0.0;
   r.num_same = 0;
   r.prev_value = FE_NA;
  }

void FE_RollAdd(SRollMean &r, const double val)
  {
   if(FE_IsNA(val))
      return;
   r.nobs++;
   double y = val - r.comp_add;
   double t = r.sum_x + y;
   r.comp_add = t - r.sum_x - y;
   r.sum_x = t;
   if(val < 0.0)
      r.neg_ct++;
   if(val == r.prev_value)
      r.num_same++;
   else
      r.num_same = 1;
   r.prev_value = val;
  }

void FE_RollRemove(SRollMean &r, const double val)
  {
   if(FE_IsNA(val))
      return;
   r.nobs--;
   double y = -val - r.comp_rem;
   double t = r.sum_x + y;
   r.comp_rem = t - r.sum_x - y;
   r.sum_x = t;
   if(val < 0.0)
      r.neg_ct--;
  }

double FE_RollValue(const SRollMean &r)
  {
   if(r.nobs >= r.window && r.nobs > 0)
     {
      double res = r.sum_x / (double)r.nobs;
      if(r.num_same >= r.nobs)
         res = r.prev_value;
      else
         if(r.neg_ct == 0 && res < 0.0)
            res = 0.0;
         else
            if(r.neg_ct == r.nobs && res > 0.0)
               res = 0.0;
      return res;
     }
   return FE_NA;
  }

//--- src[i] を加え、i 番目の値を返す（start=max(0,i+1-w), end=i+1 の固定窓）
double FE_RollPush(SRollMean &r, const double &src[], const int i)
  {
   if(i == 0)
     {
      FE_RollReset(r, r.window);
      r.prev_value = src[0];
      FE_RollAdd(r, src[0]);
     }
   else
     {
      int s = i + 1 - r.window;
      if(s < 0)
         s = 0;
      int sp = i - r.window;
      if(sp < 0)
         sp = 0;
      for(int j = sp; j < s; j++)
         FE_RollRemove(r, src[j]);
      FE_RollAdd(r, src[i]);
     }
   return FE_RollValue(r);
  }

//+------------------------------------------------------------------+
//| 暦（SPEC §2.6・付録C。Python の calendar_sets と同じ）             |
//+------------------------------------------------------------------+
int FE_DateKey(const int y, const int m, const int d)
  {
   return y * 10000 + m * 100 + d;
  }

datetime FE_MakeDate(const int y, const int m, const int d)
  {
   MqlDateTime s;
   s.year = y;
   s.mon = m;
   s.day = d;
   s.hour = 0;
   s.min = 0;
   s.sec = 0;
   s.day_of_week = 0;
   s.day_of_year = 0;
   return StructToTime(s);
  }

//--- 曜日（0=日 … 6=土）。1970-01-01 は木曜
int FE_DayOfWeek(const datetime t)
  {
   long dn = (long)t / 86400;
   return (int)((dn + 4) % 7);
  }

int FE_KeyOfTime(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return FE_DateKey(s.year, s.mon, s.day);
  }

//--- Good Friday（復活祭の2日前。付録C）
int FE_GoodFridayKey(const int y)
  {
   int a = y % 19;
   int b = y / 100;
   int c = y % 100;
   int d = b / 4;
   int e = b % 4;
   int f = (b + 8) / 25;
   int g = (b - f + 1) / 3;
   int h = (19 * a + b - d - g + 15) % 30;
   int i = c / 4;
   int k = c % 4;
   int l = (32 + 2 * e + 2 * i - h - k) % 7;
   int m = (a + 11 * h + 22 * l) / 451;
   int month = (h + l - 7 * m + 114) / 31;
   int day = (h + l - 7 * m + 114) % 31 + 1;
   datetime easter = FE_MakeDate(y, month, day);
   return FE_KeyOfTime((datetime)((long)easter - 2 * 86400));
  }

//--- 米感謝祭（11月第4木曜）の翌金曜
int FE_ThanksgivingFridayKey(const int y)
  {
   datetime nov1 = FE_MakeDate(y, 11, 1);
   int pyWd = (FE_DayOfWeek(nov1) + 6) % 7;                 // Python の weekday()（月=0）
   int add = ((3 - pyWd) % 7 + 7) % 7 + 21;
   return FE_KeyOfTime((datetime)((long)nov1 + (long)(add + 1) * 86400));
  }

//--- 米独立記念日（土曜なら前日、日曜なら翌日）
int FE_July4Key(const int y)
  {
   datetime j4 = FE_MakeDate(y, 7, 4);
   int pyWd = (FE_DayOfWeek(j4) + 6) % 7;
   if(pyWd == 5)
      return FE_KeyOfTime((datetime)((long)j4 - 86400));
   if(pyWd == 6)
      return FE_KeyOfTime((datetime)((long)j4 + 86400));
   return FE_DateKey(y, 7, 4);
  }

bool FE_InList(const int &arr[], const int key)
  {
   int n = ArraySize(arr);
   for(int i = 0; i < n; i++)
      if(arr[i] == key)
         return true;
   return false;
  }

//--- "YYYY.MM.DD;YYYY.MM.DD" → 日付キーの配列
int FE_ParseDateList(const string text, int &keys[])
  {
   ArrayResize(keys, 0);
   string s = text;
   StringReplace(s, ",", ";");
   string parts[];
   int n = StringSplit(s, StringGetCharacter(";", 0), parts);
   int cnt = 0;
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringTrimLeft(p);
      StringTrimRight(p);
      if(StringLen(p) < 8)
         continue;
      StringReplace(p, "-", ".");
      StringReplace(p, "/", ".");
      datetime t = StringToTime(p);
      if(t <= 0)
         continue;
      ArrayResize(keys, cnt + 1);
      keys[cnt] = FE_KeyOfTime(t);
      cnt++;
     }
   return cnt;
  }

//+------------------------------------------------------------------+
//| 銘柄名 → 表の名前（先頭6文字。GOLD〜 は XAUUSD）と名目スプレッド   |
//+------------------------------------------------------------------+
string FE_SymbolBase(const string sym)
  {
   string s = sym;
   StringToUpper(s);
   if(StringFind(s, "GOLD") == 0)
      return "XAUUSD";
   if(StringLen(s) > 6)
      s = StringSubstr(s, 0, 6);
   return s;
  }

//--- SPEC §10.3 の s_nom（価格単位）。表になければ -1
double FE_NominalSpread(const string base)
  {
   if(base == "EURUSD")
      return 0.00010;
   if(base == "GBPUSD")
      return 0.00015;
   if(base == "USDJPY")
      return 0.010;
   if(base == "EURJPY")
      return 0.015;
   if(base == "GBPJPY")
      return 0.025;
   if(base == "AUDUSD")
      return 0.00012;
   if(base == "USDCAD")
      return 0.00015;
   if(base == "AUDJPY")
      return 0.015;
   if(base == "XAUUSD")
      return 0.30;
   return -1.0;
  }

//+------------------------------------------------------------------+
//| 表示用の文字列                                                    |
//+------------------------------------------------------------------+
string FE_CodeName(const int code)
  {
   switch(code)
     {
      case RC_R00:
         return "R00";
      case RC_R01A:
         return "R01A";
      case RC_R01:
         return "R01";
      case RC_R02:
         return "R02";
      case RC_R03:
         return "R03";
      case RC_R04:
         return "R04";
      case RC_R05:
         return "R05";
      case RC_R06:
         return "R06";
      case RC_R07:
         return "R07";
      case RC_R08:
         return "R08";
      case RC_R09:
         return "R09";
      case RC_R10:
         return "R10";
      case RC_R11:
         return "R11";
      case RC_R12:
         return "R12";
      case RC_R13:
         return "R13";
      case RC_R14:
         return "R14";
      case RC_R15:
         return "R15";
      case RC_R16:
         return "R16";
      case RC_OK:
         return "OK";
      case RC_ARMED:
         return "ARMED";
      case RC_UPDATE:
         return "UPDATE";
      case RC_LOSE:
         return "LOSE";
      case RC_T1:
         return "T1";
      case RC_T2:
         return "T2";
      case RC_T3:
         return "T3";
      case RC_T4:
         return "T4";
      case RC_T5:
         return "T5";
     }
   return "";
  }

//--- 理由コードの短い説明（通知・パネル用）
string FE_CodeDesc(const int code)
  {
   switch(code)
     {
      case RC_R00:
         return "指標の準備未了";
      case RC_R01:
         return "4Hダウ不成立";
      case RC_R02:
         return "押しが4H MA未達";
      case RC_R03:
         return "押しの内側に1H転換点なし";
      case RC_R04:
         return "切上げ(切下げ)の崩れ";
      case RC_R05:
         return "消化済み";
      case RC_R06:
         return "約定済みのセットアップ";
      case RC_R07:
         return "G3遅すぎ";
      case RC_R08:
         return "4H MAが逆向き";
      case RC_R09:
         return "R過小";
      case RC_R10:
         return "R過大";
      case RC_R11:
         return "日足逆行";
      case RC_R12:
         return "MA乖離";
      case RC_R13:
         return "1H転換型でない";
      case RC_R14:
         return "背後の支えなし";
      case RC_R15:
         return "反対勢力が近い";
      case RC_R16:
         return "目標が近い";
      case RC_ARMED:
         return "待機注文あり";
      case RC_UPDATE:
         return "待機注文あり";
      case RC_LOSE:
         return "反対側に劣後";
      case RC_T1:
         return "休場日";
      case RC_T2:
         return "新規停止";
      case RC_T3:
         return "ロールオーバー";
      case RC_T4:
         return "建玉あり";
      case RC_T5:
         return "決済足";
     }
   return "";
  }

string FE_ReasonName(const int reason)
  {
   switch(reason)
     {
      case XR_SL:
         return "SL";
      case XR_TRAIL:
         return "TRAIL";
      case XR_SLGAP:
         return "SL_gap";
      case XR_WEEKEND:
         return "WEEKEND";
      case XR_GAP:
         return "GAP_FALLBACK";
      case XR_END:
         return "END";
     }
   return "OTHER";
  }

//--- 支えの種類（Python の '+'.join(sorted(types)) と同じ並び）
string FE_SupText(const int mask)
  {
   string s = "";
   if((mask & SUP_FLIP) != 0)
      s = "FLIP";
   if((mask & SUP_HZ) != 0)
      s = (StringLen(s) > 0) ? s + "+HZ" : "HZ";
   if((mask & SUP_KEY) != 0)
      s = (StringLen(s) > 0) ? s + "+KEY" : "KEY";
   return s;
  }

//--- グレード（SPEC §9）
string FE_Grade(const int score)
  {
   if(score >= 80)
      return "S";
   if(score >= 65)
      return "A";
   if(score >= 50)
      return "B";
   return "C";
  }

string FE_Time(const datetime t)
  {
   return TimeToString(t, TIME_DATE | TIME_MINUTES);
  }

string FE_EvalHeader(void)
  {
   return "bar_time,dir,pattern,key_time,code,price,sl,R,r_atr,depth,slope80,gap,conv,rel,T_D1,T_BIG,T_SMALL,n_sup,sup,rr_cf,tp1,S1,S2,S3,S4,S5,S6,score,phase";
  }

string FE_EvalCsv(const SEvalRow &r)
  {
   string c = ",";
   int st = r.s.stage;
   string line = FE_Time(r.bar_time) + c + IntegerToString(r.dir) + c + IntegerToString(r.pattern) + c;
   line += ((st >= 2) ? FE_Time(r.s.key_time) : "") + c;
   line += FE_CodeName(r.code) + c;
   line += ((st >= 3) ? DoubleToString(r.s.price, 10) : "") + c;
   line += ((st >= 3) ? DoubleToString(r.s.sl, 10) : "") + c;
   line += ((st >= 3) ? DoubleToString(r.s.R, 10) : "") + c;
   line += ((st >= 3) ? DoubleToString(r.s.r_atr, 6) : "") + c;
   line += ((st >= 1) ? DoubleToString(r.s.depth, 6) : "") + c;
   line += ((st >= 1) ? DoubleToString(r.s.slope, 6) : "") + c;
   line += ((st >= 4 && r.s.gap_valid) ? DoubleToString(r.s.gap, 6) : "") + c;
   line += ((st >= 1) ? DoubleToString(r.s.conv, 6) : "") + c;
   line += ((st >= 3) ? IntegerToString(r.s.rel) : "") + c;
   line += IntegerToString(r.tD1) + c + IntegerToString(r.tBig) + c + IntegerToString(r.tSmall) + c;
   line += ((st >= 5) ? IntegerToString(r.s.n_sup) : "") + c;
   line += ((st >= 5) ? FE_SupText(r.s.sup_mask) : "") + c;
   line += ((st >= 6) ? DoubleToString(r.s.rr_cf, 6) : "") + c;
   line += ((st >= 7) ? DoubleToString(r.s.tp1, 10) : "") + c;
   if(st >= 7)
      line += IntegerToString(r.s.s1) + c + IntegerToString(r.s.s2) + c + IntegerToString(r.s.s3) + c +
              IntegerToString(r.s.s4) + c + IntegerToString(r.s.s5) + c + IntegerToString(r.s.s6) + c +
              IntegerToString(r.s.score) + c;
   else
      line += ",,,,,,,";
   line += (r.phase == 0) ? "REPLAY" : "LIVE";
   return line;
  }

string FE_TradeHeader(void)
  {
   return "entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,bars_held,key_time,score,pattern,exit_price,mfe_r,mae_r,phase";
  }

string FE_TradeCsv(const STrade &tr)
  {
   string c = ",";
   string line = FE_Time(tr.entry_time) + c + IntegerToString(tr.dir) + c + DoubleToString(tr.entry, 10) + c +
                 DoubleToString(tr.init_sl, 10) + c + FE_Time(tr.exit_time) + c + FE_ReasonName(tr.reason) + c +
                 DoubleToString(tr.r, 8) + c + IntegerToString(tr.bars_held) + c + FE_Time(tr.key_time) + c +
                 IntegerToString(tr.score) + c + IntegerToString(tr.pattern) + c + DoubleToString(tr.exit_price, 10) + c +
                 DoubleToString(tr.mfe_r, 4) + c + DoubleToString(tr.mae_r, 4) + c;
   line += (tr.phase == 0) ? "REPLAY" : "LIVE";
   return line;
  }

//+------------------------------------------------------------------+
//| スイング帳簿（SPEC §4。fusion/indicators.py の SwingBook と同じ）  |
//|  足 j のスイングは足 j+N の確定時に帳簿へ足す（増分方式）。         |
//|  取り出しは max(t−LB+2, N+1) ≤ j ≤ t−N を新しい順に最大 k 個。     |
//+------------------------------------------------------------------+
class CSwingBook
  {
public:
   int               m_depth;
   int               m_lb;
   int               m_hi[];
   int               m_lo[];
   int               m_nh;
   int               m_nl;

                     CSwingBook(void);
   void              Init(const int depth, const int lb);
   void              AddHigh(const int j);
   void              AddLow(const int j);
   int               LastLE(const int &arr[], const int n, const int v) const;
   int               FirstGE(const int &arr[], const int n, const int v) const;
   int               Latest(const int &arr[], const int n, const int t, const int k, int &out[]) const;
   int               Highs(const int t, const int k, int &out[]) const;
   int               Lows(const int t, const int k, int &out[]) const;
   int               HighBefore(const int idx) const;
   int               LowBefore(const int idx) const;
  };

CSwingBook::CSwingBook(void)
  {
   m_depth = 3;
   m_lb = 400;
   m_nh = 0;
   m_nl = 0;
  }

void CSwingBook::Init(const int depth, const int lb)
  {
   m_depth = depth;
   m_lb = lb;
   m_nh = 0;
   m_nl = 0;
   ArrayResize(m_hi, 0, 4096);
   ArrayResize(m_lo, 0, 4096);
  }

void CSwingBook::AddHigh(const int j)
  {
   ArrayResize(m_hi, m_nh + 1, 4096);
   m_hi[m_nh] = j;
   m_nh++;
  }

void CSwingBook::AddLow(const int j)
  {
   ArrayResize(m_lo, m_nl + 1, 4096);
   m_lo[m_nl] = j;
   m_nl++;
  }

//--- 昇順の arr[0..n) で値が v 以下の最後の位置（なければ -1）
int CSwingBook::LastLE(const int &arr[], const int n, const int v) const
  {
   int lo = 0;
   int hi = n - 1;
   int ans = -1;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(arr[mid] <= v)
        {
         ans = mid;
         lo = mid + 1;
        }
      else
         hi = mid - 1;
     }
   return ans;
  }

//--- 昇順の arr[0..n) で値が v 以上の最初の位置（なければ n）
int CSwingBook::FirstGE(const int &arr[], const int n, const int v) const
  {
   int lo = 0;
   int hi = n - 1;
   int ans = n;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(arr[mid] >= v)
        {
         ans = mid;
         hi = mid - 1;
        }
      else
         lo = mid + 1;
     }
   return ans;
  }

int CSwingBook::Latest(const int &arr[], const int n, const int t, const int k, int &out[]) const
  {
   if(ArraySize(out) < k)
      ArrayResize(out, k);
   if(t < 0)
      return 0;
   int hiIdx = t - m_depth;
   int loIdx = t - m_lb + 2;
   if(loIdx < m_depth + 1)
      loIdx = m_depth + 1;                 // Python と同じく先頭の depth+1 本は対象外
   int p = LastLE(arr, n, hiIdx);
   int cnt = 0;
   while(p >= 0 && cnt < k)
     {
      int j = arr[p];
      if(j < loIdx)
         break;
      out[cnt] = j;
      cnt++;
      p--;
     }
   return cnt;
  }

int CSwingBook::Highs(const int t, const int k, int &out[]) const
  {
   return Latest(m_hi, m_nh, t, k, out);
  }

int CSwingBook::Lows(const int t, const int k, int &out[]) const
  {
   return Latest(m_lo, m_nl, t, k, out);
  }

//--- idx より前（idx 未満）で最新のスイング（範囲の制限なし。状態機械用）
int CSwingBook::HighBefore(const int idx) const
  {
   int p = LastLE(m_hi, m_nh, idx - 1);
   return (p >= 0) ? m_hi[p] : -1;
  }

int CSwingBook::LowBefore(const int idx) const
  {
   int p = LastLE(m_lo, m_nl, idx - 1);
   return (p >= 0) ? m_lo[p] : -1;
  }

//+------------------------------------------------------------------+
//| 持続型ダウ状態機械（SPEC §5.3。strategy.py の dow_machine と同じ）  |
//|  初回に読込先頭から再生し、以後は新しい足ごとに1歩ずつ進める。      |
//+------------------------------------------------------------------+
class CDowMachine
  {
public:
   int               m_state;     // T ∈ {+1, 0, −1}
   int               m_end;       // END（終了の兆し）
   int               m_pl;        // PLi
   int               m_ph;        // PHi
   double            m_x;         // X（FE_NA=未設定）
   bool              m_shUsed;    // 直近の確定高値はすでに上抜け済みか（used_h）
   bool              m_slUsed;    // 直近の確定安値はすでに下抜け済みか（used_l）
   char              m_T[];       // 足ごとの T
   char              m_E[];       // 足ごとの END

                     CDowMachine(void);
   void              Init(void);
  };

CDowMachine::CDowMachine(void)
  {
   Init();
  }

void CDowMachine::Init(void)
  {
   m_state = 0;
   m_end = 0;
   m_pl = -1;
   m_ph = -1;
   m_x = FE_NA;
   m_shUsed = false;
   m_slUsed = false;
   ArrayResize(m_T, 0, 16384);
   ArrayResize(m_E, 0, 16384);
  }

//+------------------------------------------------------------------+
//| 約定済み集合（key=(方向, SH の足)。1セットアップにつき約定1回）     |
//+------------------------------------------------------------------+
class CKeySet
  {
public:
   int               m_dir[];
   int               m_idx[];
   int               m_n;

                     CKeySet(void);
   void              Clear(void);
   bool              Has(const int d, const int idx) const;
   void              Add(const int d, const int idx);
  };

CKeySet::CKeySet(void)
  {
   m_n = 0;
  }

void CKeySet::Clear(void)
  {
   m_n = 0;
   ArrayResize(m_dir, 0, 256);
   ArrayResize(m_idx, 0, 256);
  }

bool CKeySet::Has(const int d, const int idx) const
  {
   for(int i = m_n - 1; i >= 0; i--)
      if(m_dir[i] == d && m_idx[i] == idx)
         return true;
   return false;
  }

void CKeySet::Add(const int d, const int idx)
  {
   if(Has(d, idx))
      return;
   ArrayResize(m_dir, m_n + 1, 256);
   ArrayResize(m_idx, m_n + 1, 256);
   m_dir[m_n] = d;
   m_idx[m_n] = idx;
   m_n++;
  }

//+------------------------------------------------------------------+
//| 1銘柄の判定エンジン                                               |
//+------------------------------------------------------------------+
class CFusionEngine
  {
public:
   SFusionParams     m_p;
   int               m_xClosed[];      // 追加の休場日（日付キー）
   int               m_xEarly[];       // 追加の早仕舞い日
   //--- 足のバッファ（古い順）と指標
   int               m_n;
   datetime          m_T[];
   double            m_O[];
   double            m_H[];
   double            m_L[];
   double            m_C[];
   double            m_tr[];
   double            m_atr[];
   double            m_ma20[];
   double            m_ma80[];
   double            m_ma480[];
   SRollMean         m_rAtr;
   SRollMean         m_r20;
   SRollMean         m_r80;
   SRollMean         m_r480;
   CSwingBook        m_bs;             // SMALL（深さ3・探索400）
   CSwingBook        m_bb;             // BIG（深さ12・探索3000）
   CSwingBook        m_bd;             // D1（深さ72・探索8000）
   CDowMachine       m_ds;             // T_SMALL
   CDowMachine       m_db;             // T_BIG
   CDowMachine       m_dd;             // T_D1
   int               m_first;          // 判定開始の足（SPEC §2.7）
   //--- 仮想ブローカー（fusion/broker.py と同じ約定モデル）
   CKeySet           m_cons;
   bool              m_pendActive;
   SSetup            m_pend;
   SVPos             m_pos;
   STrade            m_trades[];
   int               m_ntrades;
   datetime          m_preDone;        // 休場明けの判定を済ませた足の時刻
   int               m_lastBar;
   int               m_phase;          // 0=再生 1=稼働
   bool              m_prevNoNew;
   bool              m_zoneBuy;
   bool              m_zoneSell;
   //--- 出力（呼び出し側が読み出して 0 に戻す）
   SFusionEvent      m_ev[];
   int               m_nev;
   SEvalRow          m_rows[];
   int               m_nrows;
   //--- 直近の評価（パネル用）
   SSetup            m_lastBuy;
   SSetup            m_lastSell;
   int               m_lastEvalBar;
   int               m_lastTcode;
   int               m_lastKind;
   bool              m_lastNoNew;
   bool              m_lastRoll;
   bool              m_lastFlat;
   //--- 作業用
   int               m_tmpA[];
   int               m_tmpB[];
   int               m_g1h[];
   int               m_g1l[];
   SLevel            m_lv[];
   int               m_nlv;
   SLvPoint          m_pts[];
   int               m_npts;
   double            m_dist[];
   SSetup            m_evl[];
   int               m_nevl;
   int               m_bestIdx;
   SSetup            m_null;

                     CFusionEngine(void);
   void              Configure(const SFusionParams &p, const string extraClosed, const string extraEarly);
   void              ResetBuffers(void);
   void              ResetTrading(void);
   //--- 足の取り込み
   bool              IsWeekendBar(const datetime t) const;
   void              AppendBar(const datetime t, const double o, const double h, const double l, const double c);
   int               Load(const MqlRates &r[], const int cnt);
   int               Sync(const MqlRates &r[], const int cnt);
   void              UpdateFirst(void);
   int               IndexOfTime(const datetime t) const;
   int               IndexOfBarContaining(const datetime t) const;
   bool              IsPivotHigh(const int j, const int N) const;
   bool              IsPivotLow(const int j, const int N) const;
   void              AdvanceDepth(CSwingBook &bk, CDowMachine &dm, const int k);
   int               DowT(const CDowMachine &dm, const int t) const;
   int               DowE(const CDowMachine &dm, const int t) const;
   //--- 時刻ルール（SPEC §2.6）
   bool              IsClosedDay(const datetime day0) const;
   bool              IsEarlyDay(const datetime day0) const;
   datetime          NextWeekday(const datetime day0) const;
   void              TimeRulesAt(const datetime barStart, bool &no_new, bool &flat, bool &roll, int &kind) const;
   void              TimeRules(const int t, bool &no_new, bool &flat, bool &roll, int &kind) const;
   bool              GapBefore(const datetime prevStart, const datetime curStart) const;
   datetime          NextFlatClose(const datetime fromBarStart) const;
   //--- 判定（SPEC §5〜§9）
   int               G1Dow2(const int t, const int d, const CSwingBook &bk);
   int               G1Dir(const int t);
   void              AddPoint(const double price, const int w, const int kind, const bool d1);
   void              CollectPoints(const CSwingBook &bk, const bool use480, const int lo, const int hi, const int w, const bool d1);
   void              AddLevel(const int a, const int b);
   int               Levels(const int t);
   int               Reject(SSetup &s, const int code);
   int               Setup(const int t, const int d, const int pattern, const CKeySet &cons, SSetup &s);
   bool              EvalBest(const int t, const CKeySet &cons, SSetup &best);
   bool              TrailCandidate(const int t, const int d, const int entryIdx, const double curSl, double &newSl, double &swPrice);
   bool              IsZone(const SSetup &s) const;
   int               InvalidCode(const int dir, const int pattern) const;
   //--- 仮想ブローカー（run_h1 のループ）
   void              PreBarGap(const datetime prevStart, const datetime curStart, const double curOpen);
   void              PreBarIndex(const int t);
   void              PreBarForming(const datetime ft, const double fo);
   void              BarProcess(const int t);
   void              ProcessBarPos(const int t, const bool entryBar);
   void              ClosePos(const datetime tm, const double price, const int reason);
   void              CloseAtEnd(void);
   //--- 出力
   void              PushEvent(const int etype, const int dir, const int code, const datetime barTime,
                               const double price, const double sl, const double prevPrice, const double prevSl,
                               const double value, const int tradeNo, const SSetup &s);
   void              PushRow(const int t, const int dir, const int pattern, const int code, const SSetup &s);
   void              Stats(int &n, int &wins, double &sumR, int &curLoss, int &maxLoss) const;
  };

CFusionEngine::CFusionEngine(void)
  {
   FE_DefaultParams(m_p);
   FE_SetupClear(m_null);
   ResetBuffers();
   ResetTrading();
  }

void CFusionEngine::Configure(const SFusionParams &p, const string extraClosed, const string extraEarly)
  {
   m_p = p;
   FE_ParseDateList(extraClosed, m_xClosed);
   FE_ParseDateList(extraEarly, m_xEarly);
   ResetBuffers();
   ResetTrading();
  }

void CFusionEngine::ResetBuffers(void)
  {
   m_n = 0;
   ArrayResize(m_T, 0, 16384);
   ArrayResize(m_O, 0, 16384);
   ArrayResize(m_H, 0, 16384);
   ArrayResize(m_L, 0, 16384);
   ArrayResize(m_C, 0, 16384);
   ArrayResize(m_tr, 0, 16384);
   ArrayResize(m_atr, 0, 16384);
   ArrayResize(m_ma20, 0, 16384);
   ArrayResize(m_ma80, 0, 16384);
   ArrayResize(m_ma480, 0, 16384);
   FE_RollReset(m_rAtr, 14);
   FE_RollReset(m_r20, 20);
   FE_RollReset(m_r80, 80);
   FE_RollReset(m_r480, 480);
   m_bs.Init(m_p.n_small, m_p.lb_small);
   m_bb.Init(m_p.n_big, m_p.lb_big);
   m_bd.Init(m_p.n_d1, m_p.lb_d1);
   m_ds.Init();
   m_db.Init();
   m_dd.Init();
   m_first = -1;
  }

void CFusionEngine::ResetTrading(void)
  {
   m_cons.Clear();
   m_pendActive = false;
   FE_SetupClear(m_pend);
   FE_PosClear(m_pos);
   ArrayResize(m_trades, 0, 1024);
   m_ntrades = 0;
   m_preDone = 0;
   m_lastBar = -1;
   m_phase = 0;
   m_prevNoNew = false;
   m_zoneBuy = false;
   m_zoneSell = false;
   m_nev = 0;
   m_nrows = 0;
   FE_SetupClear(m_lastBuy);
   FE_SetupClear(m_lastSell);
   m_lastEvalBar = -1;
   m_lastTcode = RC_NONE;
   m_lastKind = 0;
   m_lastNoNew = false;
   m_lastRoll = false;
   m_lastFlat = false;
   m_nlv = 0;
   m_npts = 0;
   m_nevl = 0;
   m_bestIdx = -1;
  }

//--- 換算後（サーバー時間 − オフセット）の土日の足は捨てる（drop_weekend）
bool CFusionEngine::IsWeekendBar(const datetime t) const
  {
   int dow = FE_DayOfWeek((datetime)((long)t - (long)m_p.server_offset_h * 3600));
   return (dow == 0 || dow == 6);
  }

//--- 確定足を1本追記して、指標・帳簿・状態機械を1歩進める
void CFusionEngine::AppendBar(const datetime t, const double o, const double h, const double l, const double c)
  {
   int k = m_n;
   ArrayResize(m_T, k + 1, 16384);
   ArrayResize(m_O, k + 1, 16384);
   ArrayResize(m_H, k + 1, 16384);
   ArrayResize(m_L, k + 1, 16384);
   ArrayResize(m_C, k + 1, 16384);
   ArrayResize(m_tr, k + 1, 16384);
   ArrayResize(m_atr, k + 1, 16384);
   ArrayResize(m_ma20, k + 1, 16384);
   ArrayResize(m_ma80, k + 1, 16384);
   ArrayResize(m_ma480, k + 1, 16384);
   m_T[k] = t;
   m_O[k] = o;
   m_H[k] = h;
   m_L[k] = l;
   m_C[k] = c;
   if(k == 0)
      m_tr[k] = FE_NA;                                   // 先頭足の TR は使わない（iATR と同じ）
   else
      m_tr[k] = MathMax(h, m_C[k - 1]) - MathMin(l, m_C[k - 1]);
   m_n = k + 1;
   m_atr[k] = FE_RollPush(m_rAtr, m_tr, k);
   m_ma20[k] = FE_RollPush(m_r20, m_C, k);
   m_ma80[k] = FE_RollPush(m_r80, m_C, k);
   m_ma480[k] = FE_RollPush(m_r480, m_C, k);
   AdvanceDepth(m_bs, m_ds, k);
   AdvanceDepth(m_bb, m_db, k);
   AdvanceDepth(m_bd, m_dd, k);
  }

//--- 初回の読込（古い順の確定足）。取引の状態は空にする
int CFusionEngine::Load(const MqlRates &r[], const int cnt)
  {
   ResetBuffers();
   ResetTrading();
   for(int i = 0; i < cnt; i++)
     {
      if(IsWeekendBar(r[i].time))
         continue;
      if(m_n > 0 && r[i].time <= m_T[m_n - 1])
         continue;
      AppendBar(r[i].time, r[i].open, r[i].high, r[i].low, r[i].close);
     }
   UpdateFirst();
   return m_n;
  }

//--- 判定開始：ATR・SMA80 が計算済みで t ≥ SLOPE_LB+80（strategy.py の first）
void CFusionEngine::UpdateFirst(void)
  {
   m_first = -1;
   for(int t = 0; t < m_n; t++)
      if(!FE_IsNA(m_atr[t]) && !FE_IsNA(m_ma80[t]) && t >= m_p.slope_lb + 80)
        {
         m_first = t;
         break;
        }
  }

//--- 直近の確定足（古い順）を受け取り、手元と重なる部分を照合してから
//    新しい足を追記・処理する。戻り値: 追記した本数、食い違えば -1
int CFusionEngine::Sync(const MqlRates &r[], const int cnt)
  {
   if(m_n <= 0)
      return -1;
   int k = -1;
   int appended = 0;
   for(int i = 0; i < cnt; i++)
     {
      datetime t = r[i].time;
      if(IsWeekendBar(t))
         continue;
      datetime last = m_T[m_n - 1];
      if(t <= last)
        {
         if(appended > 0)
            return -1;                                   // 追記の後に古い足が来た
         if(k < 0)
           {
            if(t < m_T[0])
               continue;                                 // 手元の先頭より古い足は照合しない
            k = IndexOfTime(t);
            if(k < 0)
               return -1;                                // 手元にない足が挟まっている
           }
         else
           {
            k++;
            if(k >= m_n || m_T[k] != t)
               return -1;                                // 手元の足が欠けている／増えている
           }
         if(m_O[k] != r[i].open || m_H[k] != r[i].high || m_L[k] != r[i].low || m_C[k] != r[i].close)
            return -1;                                   // 四本値が変わった
         continue;
        }
      if(appended == 0 && k != m_n - 1)
         return -1;                                      // 照合が手元の最後の足まで届かない
      AppendBar(t, r[i].open, r[i].high, r[i].low, r[i].close);
      appended++;
      k = m_n - 1;
      if(m_first < 0)
         UpdateFirst();
      if(m_first >= 0 && k >= m_first)
        {
         if(m_preDone != m_T[k])
            PreBarIndex(k);
         BarProcess(k);
        }
     }
   if(appended == 0 && k >= 0 && k != m_n - 1)
      return -1;
   return appended;
  }

int CFusionEngine::IndexOfTime(const datetime t) const
  {
   int lo = 0;
   int hi = m_n - 1;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(m_T[mid] == t)
         return mid;
      if(m_T[mid] < t)
         lo = mid + 1;
      else
         hi = mid - 1;
     }
   return -1;
  }

//--- 時刻 t を含む足（形成中の足なら m_n）
int CFusionEngine::IndexOfBarContaining(const datetime t) const
  {
   if(m_n <= 0)
      return -1;
   if((long)t >= (long)m_T[m_n - 1] + 3600)
      return m_n;
   int lo = 0;
   int hi = m_n - 1;
   int ans = -1;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(m_T[mid] <= t)
        {
         ans = mid;
         lo = mid + 1;
        }
      else
         hi = mid - 1;
     }
   return ans;
  }

//--- isHigh(j,N): 新しい側 N 本より厳密に高く、古い側 N 本以上（SPEC §4）
bool CFusionEngine::IsPivotHigh(const int j, const int N) const
  {
   double v = m_H[j];
   for(int q = 1; q <= N; q++)
     {
      if(!(v > m_H[j + q]))
         return false;
      if(!(v >= m_H[j - q]))
         return false;
     }
   return true;
  }

bool CFusionEngine::IsPivotLow(const int j, const int N) const
  {
   double v = m_L[j];
   for(int q = 1; q <= N; q++)
     {
      if(!(v < m_L[j + q]))
         return false;
      if(!(v <= m_L[j - q]))
         return false;
     }
   return true;
  }

//--- 足 k の確定時：足 j=k−N のスイングを帳簿に足し、状態機械を1歩進める
void CFusionEngine::AdvanceDepth(CSwingBook &bk, CDowMachine &dm, const int k)
  {
   int N = bk.m_depth;
   int j = k - N;
   if(j >= N)
     {
      if(IsPivotHigh(j, N))
        {
         bk.AddHigh(j);
         dm.m_shUsed = false;
         if(dm.m_state == 1 && dm.m_pl >= 0 && j > dm.m_pl && !FE_IsNA(dm.m_x) && m_H[j] < dm.m_x)
            dm.m_end = 1;                                // 上昇中の高値切下げ
        }
      if(IsPivotLow(j, N))
        {
         bk.AddLow(j);
         dm.m_slUsed = false;
         if(dm.m_state == -1 && dm.m_ph >= 0 && j > dm.m_ph && !FE_IsNA(dm.m_x) && m_L[j] > dm.m_x)
            dm.m_end = 1;                                // 下降中の安値切上げ
        }
     }
   //--- 直近確定高値の初回終値上抜け
   if(bk.m_nh > 0)
     {
      int hj = bk.m_hi[bk.m_nh - 1];
      if(!dm.m_shUsed && m_C[k] > m_H[hj])
        {
         dm.m_shUsed = true;
         int a = hj + 1;
         for(int i = hj + 2; i <= k; i++)
            if(m_L[i] < m_L[a])
               a = i;
         int b = bk.LowBefore(hj);
         if(b >= 0 && m_L[a] > m_L[b])
           {
            dm.m_state = 1;                              // 安値切上げ＋高値更新＝上昇確定
            dm.m_pl = a;
            double x = m_H[a];
            for(int i2 = a + 1; i2 <= k; i2++)
               if(m_H[i2] > x)
                  x = m_H[i2];
            dm.m_x = x;
            dm.m_end = 0;
           }
         else
            if(dm.m_state == -1)
              {
               dm.m_state = 0;                           // 下降の「終了」（転換ではない）
               dm.m_end = 0;
              }
        }
     }
   //--- 直近確定安値の初回終値下抜け（同じ足では上抜け→下抜けの順）
   if(bk.m_nl > 0)
     {
      int lj = bk.m_lo[bk.m_nl - 1];
      if(!dm.m_slUsed && m_C[k] < m_L[lj])
        {
         dm.m_slUsed = true;
         int a2 = lj + 1;
         for(int i3 = lj + 2; i3 <= k; i3++)
            if(m_H[i3] > m_H[a2])
               a2 = i3;
         int b2 = bk.HighBefore(lj);
         if(b2 >= 0 && m_H[a2] < m_H[b2])
           {
            dm.m_state = -1;
            dm.m_ph = a2;
            double x2 = m_L[a2];
            for(int i4 = a2 + 1; i4 <= k; i4++)
               if(m_L[i4] < x2)
                  x2 = m_L[i4];
            dm.m_x = x2;
            dm.m_end = 0;
           }
         else
            if(dm.m_state == 1)
              {
               dm.m_state = 0;
               dm.m_end = 0;
              }
        }
     }
   if(dm.m_state == 1)
      dm.m_x = FE_IsNA(dm.m_x) ? m_H[k] : MathMax(dm.m_x, m_H[k]);
   else
      if(dm.m_state == -1)
         dm.m_x = FE_IsNA(dm.m_x) ? m_L[k] : MathMin(dm.m_x, m_L[k]);
   ArrayResize(dm.m_T, k + 1, 16384);
   ArrayResize(dm.m_E, k + 1, 16384);
   dm.m_T[k] = (char)dm.m_state;
   dm.m_E[k] = (char)dm.m_end;
  }

int CFusionEngine::DowT(const CDowMachine &dm, const int t) const
  {
   if(t < 0 || t >= ArraySize(dm.m_T))
      return 0;
   return (int)dm.m_T[t];
  }

int CFusionEngine::DowE(const CDowMachine &dm, const int t) const
  {
   if(t < 0 || t >= ArraySize(dm.m_E))
      return 0;
   return (int)dm.m_E[t];
  }

//+------------------------------------------------------------------+
//| 時刻ルール（SPEC §2.6。strategy.py の time_rules と同じ）          |
//+------------------------------------------------------------------+
bool CFusionEngine::IsClosedDay(const datetime day0) const
  {
   MqlDateTime s;
   TimeToStruct(day0, s);
   if((s.mon == 12 && s.day == 25) || (s.mon == 1 && s.day == 1))
      return true;
   int key = FE_DateKey(s.year, s.mon, s.day);
   if(m_p.is_xau && key == FE_GoodFridayKey(s.year))
      return true;
   return FE_InList(m_xClosed, key);
  }

bool CFusionEngine::IsEarlyDay(const datetime day0) const
  {
   MqlDateTime s;
   TimeToStruct(day0, s);
   if((s.mon == 12 && s.day == 24) || (s.mon == 12 && s.day == 31))
      return true;
   int key = FE_DateKey(s.year, s.mon, s.day);
   if(m_p.is_xau && (key == FE_ThanksgivingFridayKey(s.year) || key == FE_July4Key(s.year)))
      return true;
   return FE_InList(m_xEarly, key);
  }

datetime CFusionEngine::NextWeekday(const datetime day0) const
  {
   datetime n = (datetime)((long)day0 + 86400);
   while(FE_DayOfWeek(n) == 0 || FE_DayOfWeek(n) == 6)
      n = (datetime)((long)n + 86400);
   return n;
  }

//--- barStart: 足の開始時刻（サーバー時間）。kind: 1=休場日 2=早仕舞い日 3=金曜・休場前日 0=通常
void CFusionEngine::TimeRulesAt(const datetime barStart, bool &no_new, bool &flat, bool &roll, int &kind) const
  {
   long st = (long)barStart - (long)m_p.server_offset_h * 3600;     // NY+7 に換算した開始時刻
   long ct = st + 3600;                                              // 確定時刻
   MqlDateTime cs;
   TimeToStruct((datetime)ct, cs);
   double hc = cs.hour + cs.min / 60.0;
   long sd = st / 86400;
   long cd = ct / 86400;
   if(hc == 0.0 && cd > sd)
      hc = 24.0;                                                     // 翌日0:00 の確定は24
   datetime day0 = (datetime)(sd * 86400);                           // 日付＝足の開始日
   int dow = FE_DayOfWeek(day0);
   no_new = false;
   flat = false;
   kind = 0;
   if(IsClosedDay(day0))
     {
      no_new = true;
      flat = true;
      kind = 1;
     }
   else
      if(IsEarlyDay(day0))
        {
         no_new = (hc >= 17.0);
         flat = (hc >= 19.0);
         kind = 2;
        }
      else
         if(dow == 5 || IsClosedDay(NextWeekday(day0)))
           {
            no_new = (hc >= 20.0);
            flat = (hc >= 22.0);
            kind = 3;
           }
   roll = (hc >= 23.0 || hc < 1.0);
  }

void CFusionEngine::TimeRules(const int t, bool &no_new, bool &flat, bool &roll, int &kind) const
  {
   TimeRulesAt(m_T[t], no_new, flat, roll, kind);
  }

//--- 休場明け：前の足の確定から次の足の始まりまで12時間以上
bool CFusionEngine::GapBefore(const datetime prevStart, const datetime curStart) const
  {
   return ((long)curStart - (long)prevStart - 3600 >= (long)m_p.gap_fallback_h * 3600);
  }

//--- 次の決済予定（全決済になる足の確定時刻。9日先まで。なければ 0）
datetime CFusionEngine::NextFlatClose(const datetime fromBarStart) const
  {
   for(int i = 0; i <= 24 * 9; i++)
     {
      datetime b = (datetime)((long)fromBarStart + (long)i * 3600);
      if(IsWeekendBar(b))
         continue;
      bool nn = false, fl = false, rl = false;
      int kd = 0;
      TimeRulesAt(b, nn, fl, rl, kd);
      if(fl)
         return (datetime)((long)b + 3600);
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| G1：4H レベルのダウ構造（SPEC §5.1）。成立なら押しの起点 j_peak     |
//+------------------------------------------------------------------+
int CFusionEngine::G1Dow2(const int t, const int d, const CSwingBook &bk)
  {
   int nh = bk.Highs(t, 2, m_g1h);
   int nl = bk.Lows(t, 2, m_g1l);
   if(nh < 2 || nl < 2)
      return -1;
   double h0 = m_H[m_g1h[0]];
   double h1 = m_H[m_g1h[1]];
   double l0 = m_L[m_g1l[0]];
   double l1 = m_L[m_g1l[1]];
   if(d == 1)
     {
      if(h0 > h1 && l0 > l1 && m_C[t] > l0)
         return m_g1h[0];
      return -1;
     }
   if(l0 < l1 && h0 < h1 && m_C[t] < h0)
      return m_g1l[0];
   return -1;
  }

int CFusionEngine::G1Dir(const int t)
  {
   if(t < 0 || t >= m_n)
      return 0;
   if(G1Dow2(t, 1, m_bb) >= 0)
      return 1;
   if(G1Dow2(t, -1, m_bb) >= 0)
      return -1;
   return 0;
  }

//+------------------------------------------------------------------+
//| 節目エンジン（SPEC §6.2。strategy.py の levels_at と cluster）     |
//+------------------------------------------------------------------+
void CFusionEngine::AddPoint(const double price, const int w, const int kind, const bool d1)
  {
   if(ArraySize(m_pts) <= m_npts)
      ArrayResize(m_pts, m_npts + 256);
   m_pts[m_npts].price = price;
   m_pts[m_npts].w = w;
   m_pts[m_npts].kind = kind;
   m_pts[m_npts].d1 = d1;
   m_npts++;
  }

void CFusionEngine::CollectPoints(const CSwingBook &bk, const bool use480, const int lo, const int hi, const int w, const bool d1)
  {
   int a = bk.FirstGE(bk.m_hi, bk.m_nh, lo);
   int b = bk.LastLE(bk.m_hi, bk.m_nh, hi);
   for(int p = a; p <= b; p++)
     {
      int j = bk.m_hi[p];
      double ma = use480 ? m_ma480[j] : m_ma80[j];
      if(FE_IsNA(ma))
         continue;
      if(m_H[j] > ma)
         AddPoint(m_H[j], w, 1, d1);                     // 20MA の「山」だけ
     }
   a = bk.FirstGE(bk.m_lo, bk.m_nl, lo);
   b = bk.LastLE(bk.m_lo, bk.m_nl, hi);
   for(int p2 = a; p2 <= b; p2++)
     {
      int j2 = bk.m_lo[p2];
      double ma2 = use480 ? m_ma480[j2] : m_ma80[j2];
      if(FE_IsNA(ma2))
         continue;
      if(m_L[j2] < ma2)
         AddPoint(m_L[j2], w, -1, d1);                   // 「谷」だけ
     }
  }

//--- 並べ替え済みの候補点 [a, b) を1つの節目にまとめる
void CFusionEngine::AddLevel(const int a, const int b)
  {
   int cnt = b - a;
   if(cnt <= 0)
      return;
   if(ArraySize(m_lv) <= m_nlv)
      ArrayResize(m_lv, m_nlv + 64);
   double med = 0.0;
   if(cnt % 2 == 1)
      med = m_pts[a + cnt / 2].price;
   else
      med = (m_pts[a + cnt / 2 - 1].price + m_pts[a + cnt / 2].price) / 2.0;
   int touch = 0, nh = 0, nl = 0;
   bool d1 = false;
   for(int i = a; i < b; i++)
     {
      touch += m_pts[i].w;
      if(m_pts[i].kind == 1)
         nh++;
      if(m_pts[i].kind == -1)
         nl++;
      if(m_pts[i].d1)
         d1 = true;
     }
   m_lv[m_nlv].price = med;
   m_lv[m_nlv].touch = touch;
   m_lv[m_nlv].nh = nh;
   m_lv[m_nlv].nl = nl;
   m_lv[m_nlv].d1 = d1;
   m_nlv++;
  }

//--- t 時点で確定済みのスイングから節目を作り直す（m_lv[0..m_nlv)）
int CFusionEngine::Levels(const int t)
  {
   m_npts = 0;
   m_nlv = 0;
   CollectPoints(m_bb, false, t - m_p.lv_win_big + 1, t - m_bb.m_depth, 1, false);
   CollectPoints(m_bd, true, t - m_p.lv_win_d1 + 1, t - m_bd.m_depth, 2, true);
   if(m_npts == 0)
      return 0;
   //--- 価格の昇順（安定な挿入ソート）
   for(int i = 1; i < m_npts; i++)
     {
      SLvPoint key;
      key = m_pts[i];
      int j = i - 1;
      while(j >= 0 && m_pts[j].price > key.price)
        {
         m_pts[j + 1] = m_pts[j];
         j--;
        }
      m_pts[j + 1] = key;
     }
   double tol = m_p.tol_lv * m_atr[t];
   int gs = 0;
   for(int i2 = 1; i2 < m_npts; i2++)
     {
      double p = m_pts[i2].price;
      if(p - m_pts[gs].price <= 2 * tol && p - m_pts[i2 - 1].price <= tol)
         continue;
      AddLevel(gs, i2);
      gs = i2;
     }
   AddLevel(gs, m_npts);
   return m_nlv;
  }

int CFusionEngine::Reject(SSetup &s, const int code)
  {
   s.code = code;
   return code;
  }

//+------------------------------------------------------------------+
//| 足 t の確定時点で方向 d の注文案を作る（SPEC §5〜§9）               |
//| strategy.py の setup() と同じ評価順。戻り値は理由コードか RC_OK     |
//+------------------------------------------------------------------+
int CFusionEngine::Setup(const int t, const int d, const int pattern, const CKeySet &cons, SSetup &s)
  {
   FE_SetupClear(s);
   s.dir = d;
   s.pattern = pattern;
   if(FE_IsNA(m_atr[t]) || FE_IsNA(m_ma80[t]) || t < m_p.slope_lb || FE_IsNA(m_ma80[t - m_p.slope_lb]) || m_atr[t] <= 0.0)
      return Reject(s, RC_R00);
   //--- G1（パターン③は §11.3 の環境）
   int j_peak = -1;
   bool ref480 = false;
   if(pattern == 1)
     {
      j_peak = G1Dow2(t, d, m_bb);
      if(j_peak < 0)
         return Reject(s, RC_R01);
     }
   else
     {
      if(G1Dow2(t, d, m_bb) >= 0)
         return Reject(s, RC_R01);                      // ①の局面
      j_peak = G1Dow2(t, d, m_bd);
      if(j_peak < 0)
         return Reject(s, RC_R01);
      int nbh = m_bb.Highs(t, 2, m_tmpA);
      int nbl = m_bb.Lows(t, 2, m_tmpB);
      if(nbh < 2 || nbl < 2)
         return Reject(s, RC_R01);
      double bh0 = m_H[m_tmpA[0]];
      double bh1 = m_H[m_tmpA[1]];
      double bl0 = m_L[m_tmpB[0]];
      double bl1 = m_L[m_tmpB[1]];
      bool endsig = (d == 1) ? (bl0 > bl1 || m_C[t] > bh0) : (bh0 < bh1 || m_C[t] < bl0);
      if(!endsig)
         return Reject(s, RC_R01);
      if(FE_IsNA(m_ma480[t]))
         return Reject(s, RC_R00);
      ref480 = true;
     }
   double a_t = m_atr[t];
   s.atr = a_t;
   s.j_peak = j_peak;
   double slope = (m_ma80[t] - m_ma80[t - m_p.slope_lb]) / a_t * d;
   //--- 押しの深さと MA 収束：W=(j_peak, t]（未計算の足は除く＝nanmin）
   double depth = FE_NA;
   double conv = FE_NA;
   for(int k = j_peak + 1; k <= t; k++)
     {
      double ak = m_atr[k];
      if(FE_IsNA(ak) || ak <= 0.0)
         continue;
      double rm = ref480 ? m_ma480[k] : m_ma80[k];
      if(!FE_IsNA(rm))
        {
         double v = (d == 1) ? (m_L[k] - rm) / ak : (rm - m_H[k]) / ak;
         if(FE_IsNA(depth) || v < depth)
            depth = v;
        }
      if(!FE_IsNA(m_ma20[k]) && !FE_IsNA(m_ma80[k]))
        {
         double cv = MathAbs(m_ma20[k] - m_ma80[k]) / ak;
         if(FE_IsNA(conv) || cv < conv)
            conv = cv;
        }
     }
   s.slope = slope;
   s.depth = depth;
   s.conv = conv;
   s.stage = 1;
   if(depth > m_p.zone_atr)
      return Reject(s, RC_R02);                         // G2：押しが 4H MA に届いていない
   //--- 1H 転換（SPEC §7.1。売りは鏡像）
   int j_sh = -1;
   double lvl = 0.0, l0 = 0.0, run_ext = 0.0;
   if(d == 1)
     {
      int nsh = m_bs.Highs(t, 1, m_tmpA);
      if(nsh < 1 || m_tmpA[0] <= j_peak)
         return Reject(s, RC_R03);
      j_sh = m_tmpA[0];
      lvl = m_H[j_sh];
      int nl0 = m_bs.Lows(t, m_p.l0_search, m_tmpB);
      int c0 = -1;
      for(int q = 0; q < nl0; q++)
         if(m_tmpB[q] < j_sh)
           {
            c0 = m_tmpB[q];
            break;
           }
      if(c0 < 0)
         return Reject(s, RC_R03);
      l0 = m_L[c0];
      run_ext = m_L[j_sh + 1];
      for(int k2 = j_sh + 2; k2 <= t; k2++)
         if(m_L[k2] < run_ext)
            run_ext = m_L[k2];
     }
   else
     {
      int nsl = m_bs.Lows(t, 1, m_tmpA);
      if(nsl < 1 || m_tmpA[0] <= j_peak)
         return Reject(s, RC_R03);
      j_sh = m_tmpA[0];
      lvl = m_L[j_sh];
      int nh0 = m_bs.Highs(t, m_p.l0_search, m_tmpB);
      int c1 = -1;
      for(int q2 = 0; q2 < nh0; q2++)
         if(m_tmpB[q2] < j_sh)
           {
            c1 = m_tmpB[q2];
            break;
           }
      if(c1 < 0)
         return Reject(s, RC_R03);
      l0 = m_H[c1];
      run_ext = m_H[j_sh + 1];
      for(int k3 = j_sh + 2; k3 <= t; k3++)
         if(m_H[k3] > run_ext)
            run_ext = m_H[k3];
     }
   s.key_idx = j_sh;
   s.key_time = m_T[j_sh];
   s.lvl = lvl;
   s.l0 = l0;
   s.run_ext = run_ext;
   s.stage = 2;
   if((d == 1 && run_ext <= l0) || (d == -1 && run_ext >= l0))
      return Reject(s, RC_R04);                         // 安値切上げ（高値切下げ）の崩れ
   for(int k4 = j_sh + 1; k4 <= t; k4++)
      if((d == 1 && m_C[k4] > lvl) || (d == -1 && m_C[k4] < lvl))
         return Reject(s, RC_R05);                      // 終値で更新済み＝消化済み
   if(cons.Has(d, j_sh))
      return Reject(s, RC_R06);                         // 1セットアップにつき約定1回
   double ref_t = ref480 ? m_ma480[t] : m_ma80[t];
   if(m_p.g3 && (lvl - ref_t) * d / a_t > m_p.lvl_max_atr)
      return Reject(s, RC_R07);
   if(pattern == 1 && slope < m_p.slope_min)
      return Reject(s, RC_R08);                         // MA 傾きゲート
   //--- 注文価格・損切り・R（SPEC §7.2）
   double price = lvl + d * m_p.entry_buf_atr * a_t;
   double buf = MathMax(m_p.sl_buf_atr * a_t, m_p.spread_floor * m_p.s_nom);
   int nlv = Levels(t);
   double tol_s = m_p.tol_s * a_t;
   double anchor = run_ext;
   if(m_p.sl_mode == 1)
     {
      bool found = false;
      double bestA = 0.0;
      for(int i = 0; i < nlv; i++)
        {
         if(!(m_lv[i].touch >= 2 || m_lv[i].d1))
            continue;
         double dd = (run_ext - m_lv[i].price) * d;
         if(0 <= dd && dd <= tol_s)
           {
            if(!found || (d == 1 && m_lv[i].price < bestA) || (d == -1 && m_lv[i].price > bestA))
               bestA = m_lv[i].price;
            found = true;
           }
        }
      if(found)
         anchor = bestA;
     }
   double sl = anchor - d * buf;
   double R = (price - sl) * d;
   int rel = DowT(m_dd, t) * d;
   double rmax = m_p.r_max_atr * ((m_p.d1_gate == 2 && rel == -1) ? 0.5 : 1.0);
   s.price = price;
   s.sl = sl;
   s.R = R;
   s.r_atr = R / a_t;
   s.rel = rel;
   s.stage = 3;
   if(R < m_p.r_min_atr * a_t)
      return Reject(s, RC_R09);
   if(R > rmax * a_t)
      return Reject(s, RC_R10);
   if(R <= 0)
      return Reject(s, RC_R09);
   if(m_p.d1_gate == 1 && rel == -1)
      return Reject(s, RC_R11);
   //--- 乖離（SPEC §3）
   double gap = 0.0;
   bool gapValid = false;
   if(!FE_IsNA(m_ma480[t]))
     {
      gap = (m_ma80[t] - m_ma480[t]) * d / a_t;
      gapValid = true;
     }
   bool prevValid = false;
   double gapPrev = 0.0;
   if(t >= 12)
     {
      int tp = t - 12;
      if(!FE_IsNA(m_ma80[tp]) && !FE_IsNA(m_ma480[tp]) && !FE_IsNA(m_atr[tp]) && m_atr[tp] > 0.0)
        {
         gapPrev = (m_ma80[tp] - m_ma480[tp]) * d / m_atr[tp];
         prevValid = true;
        }
     }
   bool gapBad = gapValid && prevValid && gap > m_p.gap_hi && gap > gapPrev;
   s.gap = gap;
   s.gap_valid = gapValid;
   s.gap_bad = gapBad;
   s.stage = 4;
   if(m_p.gap_gate && gapBad)
      return Reject(s, RC_R12);
   //--- 背後の支え（SPEC §6.3。B＝押しの極値）
   double pb = (d == 1) ? m_L[j_peak + 1] : m_H[j_peak + 1];
   for(int k5 = j_peak + 2; k5 <= t; k5++)
     {
      if(d == 1 && m_L[k5] < pb)
         pb = m_L[k5];
      if(d == -1 && m_H[k5] > pb)
         pb = m_H[k5];
     }
   int mask = 0;
   for(int i5 = 0; i5 < nlv; i5++)
     {
      if(MathAbs(m_lv[i5].price - pb) <= tol_s)
        {
         if(m_lv[i5].touch >= 2)
            mask |= SUP_HZ;
         if((d == 1 && m_lv[i5].nh >= 1 && m_lv[i5].price < m_C[t]) || (d == -1 && m_lv[i5].nl >= 1 && m_lv[i5].price > m_C[t]))
            mask |= SUP_FLIP;
        }
     }
   int nk = (d == 1) ? m_bb.Lows(t, 4, m_tmpA) : m_bb.Highs(t, 4, m_tmpA);
   for(int q3 = 0; q3 < nk; q3++)
     {
      if(m_tmpA[q3] < j_peak)
        {
         double kp = (d == 1) ? m_L[m_tmpA[q3]] : m_H[m_tmpA[q3]];
         if(MathAbs(kp - pb) <= tol_s)
            mask |= SUP_KEY;
         break;
        }
     }
   int nsup = 0;
   if((mask & SUP_HZ) != 0)
      nsup++;
   if((mask & SUP_FLIP) != 0)
      nsup++;
   if((mask & SUP_KEY) != 0)
      nsup++;
   s.sup_mask = mask;
   s.n_sup = nsup;
   s.stage = 5;
   if(m_p.support_gate && nsup == 0)
      return Reject(s, RC_R14);
   //--- 前方の反対勢力と目標（SPEC §6.4）
   double tol_lv = m_p.tol_lv * a_t;
   double th = (d == 1) ? m_H[j_peak] : m_L[j_peak];
   for(int k6 = j_peak + 1; k6 <= t; k6++)
     {
      if(d == 1 && m_H[k6] > th)
         th = m_H[k6];
      if(d == -1 && m_L[k6] < th)
         th = m_L[k6];
     }
   s.th = th;
   bool hasCf = false;
   double cfMin = 0.0;
   for(int i6 = 0; i6 < nlv; i6++)
     {
      if((m_lv[i6].price - th) * d > tol_lv)
        {
         bool scope = (m_p.cf_scope == 0) ? (m_lv[i6].touch >= m_p.cf_min_touch) : m_lv[i6].d1;
         if(scope)
           {
            double dist = (m_lv[i6].price - price) * d;
            if(!hasCf || dist < cfMin)
               cfMin = dist;
            hasCf = true;
           }
        }
     }
   if(!FE_IsNA(m_ma480[t]) && (m_ma480[t] - price) * d > 0)
     {
      double dist2 = (m_ma480[t] - price) * d;
      if(!hasCf || dist2 < cfMin)
         cfMin = dist2;
      hasCf = true;
     }
   double rr_cf = hasCf ? cfMin / R : 99.0;
   s.rr_cf = rr_cf;
   s.stage = 6;
   if(m_p.clear_gate && rr_cf < m_p.rr_cf)
      return Reject(s, RC_R15);
   //--- 目標候補 TG（price より先のもの。距離の昇順）
   int nd = 0;
   if(ArraySize(m_dist) < nlv + 2)
      ArrayResize(m_dist, nlv + 2);
   double v0 = (th - price) * d;
   if(v0 > 0)
     {
      m_dist[nd] = v0;
      nd++;
     }
   for(int i7 = 0; i7 < nlv; i7++)
     {
      if(m_lv[i7].touch >= 2 || m_lv[i7].d1)
        {
         double v1 = (m_lv[i7].price - price) * d;
         if(v1 > 0)
           {
            m_dist[nd] = v1;
            nd++;
           }
        }
     }
   if(!FE_IsNA(m_ma480[t]))
     {
      double v2 = (m_ma480[t] - price) * d;
      if(v2 > 0)
        {
         m_dist[nd] = v2;
         nd++;
        }
     }
   for(int i8 = 1; i8 < nd; i8++)
     {
      double key = m_dist[i8];
      int j8 = i8 - 1;
      while(j8 >= 0 && m_dist[j8] > key)
        {
         m_dist[j8 + 1] = m_dist[j8];
         j8--;
        }
      m_dist[j8 + 1] = key;
     }
   double near_r = (nd > 0) ? m_dist[0] / R : 99.0;
   double t1 = -1.0;
   for(int i9 = 0; i9 < nd; i9++)
      if(m_dist[i9] / R >= m_p.tp1_min_r)
        {
         t1 = m_dist[i9];
         break;
        }
   double tp1 = price + d * ((t1 >= 0.0) ? t1 : m_p.tp_default_r * R);
   s.near_r = near_r;
   s.tp1 = tp1;
   s.tp2_valid = false;
   double lim = (tp1 - price) * d + tol_lv;
   for(int i10 = 0; i10 < nd; i10++)
      if(m_dist[i10] > lim)
        {
         s.tp2 = price + d * m_dist[i10];
         s.tp2_valid = true;
         break;
        }
   //--- スコア（SPEC §9。情報用）
   s.s1 = (slope >= 0.10) ? 20 : ((slope >= 0) ? 10 : 0);
   s.s2 = (depth <= 0) ? 15 : 8;
   s.s3 = (nsup >= 2) ? 15 : ((nsup == 1) ? 8 : 0);
   s.s4 = (rel == 1) ? 20 : ((rel == 0) ? 10 : 0);
   s.s5 = (rr_cf >= 3) ? 15 : ((rr_cf >= 2) ? 10 : ((rr_cf >= 1) ? 5 : 0));
   s.s6 = (gapBad ? 0 : 8) + ((conv <= m_p.conv_atr) ? 7 : 0);
   s.score = s.s1 + s.s2 + s.s3 + s.s4 + s.s5 + s.s6;
   s.stage = 7;
   s.code = RC_OK;
   return RC_OK;
  }

//--- 新規判定（買い→売り、スコアの高い方、同点は買い。①がなければ③）
//    評価した案は m_evl[0..m_nevl)（[0]=①買い [1]=①売り）
bool CFusionEngine::EvalBest(const int t, const CKeySet &cons, SSetup &best)
  {
   if(ArraySize(m_evl) < 4)
      ArrayResize(m_evl, 4);
   m_nevl = 0;
   m_bestIdx = -1;
   for(int pi = 0; pi < 2; pi++)
     {
      int pattern = (pi == 0) ? 1 : 3;
      if(pattern == 3 && (m_bestIdx >= 0 || !m_p.p3))
         break;
      for(int di = 0; di < 2; di++)
        {
         int d = (di == 0) ? 1 : -1;
         Setup(t, d, pattern, cons, m_evl[m_nevl]);
         if(m_evl[m_nevl].code == RC_OK && (m_bestIdx < 0 || m_evl[m_nevl].score > m_evl[m_bestIdx].score))
            m_bestIdx = m_nevl;
         m_nevl++;
        }
     }
   if(m_bestIdx < 0)
      return false;
   best = m_evl[m_bestIdx];
   return true;
  }

//--- 構造トレール（SPEC §10.1）：最新の BIG 安値が約定足idx−N_BIG より後なら
//    new_SL = sw.p − max(0.2ATR, 3·s_nom)。new_SL>SL かつ C[t]>new_SL のときだけ
bool CFusionEngine::TrailCandidate(const int t, const int d, const int entryIdx, const double curSl, double &newSl, double &swPrice)
  {
   int nsw = (d == 1) ? m_bb.Lows(t, 1, m_tmpA) : m_bb.Highs(t, 1, m_tmpA);
   if(nsw < 1)
      return false;
   if(!(m_tmpA[0] > entryIdx - m_bb.m_depth))
      return false;
   if(FE_IsNA(m_atr[t]))
      return false;
   double bf = MathMax(m_p.sl_buf_atr * m_atr[t], m_p.spread_floor * m_p.s_nom);
   double swp = (d == 1) ? m_L[m_tmpA[0]] : m_H[m_tmpA[0]];
   double ns = swp - d * bf;
   if((ns - curSl) * d > 0 && (m_C[t] - ns) * d > 0)
     {
      newSl = ns;
      swPrice = swp;
      return true;
     }
   return false;
  }

//--- ZONE：G1・G2・MA 傾きは OK だがトリガーが未成立（SPEC §15）
bool CFusionEngine::IsZone(const SSetup &s) const
  {
   if(s.code == RC_R09 || s.code == RC_R10)
      return true;
   if((s.code == RC_R03 || s.code == RC_R04 || s.code == RC_R05) && s.stage >= 1 && s.pattern == 1)
      return (s.slope >= m_p.slope_min);
   return false;
  }

int CFusionEngine::InvalidCode(const int dir, const int pattern) const
  {
   for(int i = 0; i < m_nevl; i++)
      if(m_evl[i].dir == dir && m_evl[i].pattern == pattern)
         return m_evl[i].code;
   for(int j = 0; j < m_nevl; j++)
      if(m_evl[j].dir == dir)
         return m_evl[j].code;
   return RC_NONE;
  }

//+------------------------------------------------------------------+
//| 仮想ブローカー：run_h1 のループ（SPEC §14）                         |
//+------------------------------------------------------------------+
//--- 1) 休場明け：待機注文を取消し、建玉はその足の始値（決済側）で決済
void CFusionEngine::PreBarGap(const datetime prevStart, const datetime curStart, const double curOpen)
  {
   if(!GapBefore(prevStart, curStart))
      return;
   bool hadPend = m_pendActive;
   SSetup prev;
   prev = m_pend;
   m_pendActive = false;
   bool hadPos = m_pos.active;
   int pdir = m_pos.dir;
   if(m_pos.active)
      ClosePos(curStart, curOpen - m_pos.dir * m_p.s_nom / 2, XR_GAP);
   if(hadPend || hadPos)
      PushEvent(EV_GAP, hadPos ? pdir : prev.dir, (hadPos ? 2 : 0) + (hadPend ? 1 : 0), curStart, curOpen, 0.0,
                prev.price, prev.sl, 0.0, hadPos ? m_ntrades - 1 : -1, prev);
  }

void CFusionEngine::PreBarIndex(const int t)
  {
   if(t >= 1)
      PreBarGap(m_T[t - 1], m_T[t], m_O[t]);
   m_preDone = m_T[t];
  }

//--- 形成中の足が始まった時点で 1) を行う（実時間でも始値で判定できる）
void CFusionEngine::PreBarForming(const datetime ft, const double fo)
  {
   if(m_n <= 0 || m_first < 0 || m_n < m_first)
      return;
   if(IsWeekendBar(ft) || ft <= m_T[m_n - 1] || m_preDone == ft)
      return;
   PreBarGap(m_T[m_n - 1], ft, fo);
   m_preDone = ft;
  }

//--- 足 t の 2)〜6)（足 t の確定時）
void CFusionEngine::BarProcess(const int t)
  {
   datetime tm = m_T[t];
   double o = m_O[t];
   double h = m_H[t];
   double l = m_L[t];
   double c = m_C[t];
   m_lastBar = t;
   //--- 2) 逆指値の約定判定（SPEC §7.4。Ask 高値／Bid 安値、窓開けは始値）
   if(m_pendActive && !m_pos.active)
     {
      int d = m_pend.dir;
      double sp = m_pend.price;
      bool touched = (d == 1) ? (h + m_p.s_nom / 2 >= sp) : (l - m_p.s_nom / 2 <= sp);
      if(touched)
        {
         double o_side = o + d * m_p.s_nom / 2;
         double fill_mid = ((d == 1) ? MathMax(o_side, sp) : MathMin(o_side, sp)) - d * m_p.s_nom / 2;
         double entry = fill_mid + d * m_p.s_nom / 2;
         if((entry - m_pend.sl) * d > 0)
           {
            FE_PosClear(m_pos);
            m_pos.active = true;
            m_pos.dir = d;
            m_pos.entry_time = tm;
            m_pos.entry_idx = t;
            m_pos.entry = entry;
            m_pos.sl = m_pend.sl;
            m_pos.init_sl = m_pend.sl;
            m_pos.s = m_pend;
            m_cons.Add(d, m_pend.key_idx);
            PushEvent(EV_FILLED, d, 0, tm, entry, m_pend.sl, sp, m_pend.sl, 0.0, -1, m_pend);
            ProcessBarPos(t, true);
           }
         m_pendActive = false;
        }
     }
   //--- 3) 建玉の足処理（窓開け → SL 優先。約定足は除く）
   if(m_pos.active && m_pos.entry_time != tm)
      ProcessBarPos(t, false);
   //--- 4) 確定時の管理：週末・休場前の決済、構造トレール
   bool no_new = false, flat = false, roll = false;
   int kind = 0;
   TimeRules(t, no_new, flat, roll, kind);
   m_lastNoNew = no_new;
   m_lastRoll = roll;
   m_lastKind = kind;
   m_lastFlat = flat;
   if(m_pos.active)
     {
      if(flat)
         ClosePos((datetime)((long)tm + 3600), c - m_pos.dir * m_p.s_nom / 2, XR_WEEKEND);
      else
        {
         double nsl = 0.0, swp = 0.0;
         if(TrailCandidate(t, m_pos.dir, m_pos.entry_idx, m_pos.sl, nsl, swp))
           {
            double old = m_pos.sl;
            m_pos.sl = nsl;                              // 次の足から有効
            m_pos.trails++;
            PushEvent(EV_TRAIL, m_pos.dir, 0, tm, nsl, nsl, old, swp, 0.0, -1, m_pos.s);
           }
        }
     }
   bool edge = (no_new && !m_prevNoNew);
   m_prevNoNew = no_new;
   //--- 5) 時刻・建玉による見送り（ファネルに数えず T コードで記録）
   int tcode = RC_NONE;
   if(flat)
      tcode = (kind == 1) ? RC_T1 : RC_T5;
   else
      if(m_pos.active)
         tcode = RC_T4;
      else
         if(no_new)
            tcode = RC_T2;
         else
            if(roll)
               tcode = RC_T3;
   if(tcode != RC_NONE)
     {
      bool had = m_pendActive && (tcode != RC_T4);
      SSetup prev;
      prev = m_pend;
      if(tcode != RC_T4)
         m_pendActive = false;
      if(edge && kind >= 2 && !flat)
         PushEvent(EV_NONEW, prev.dir, had ? 1 : 0, tm, prev.price, prev.sl, prev.price, prev.sl, (double)kind, -1, prev);
      else
         if(had)
            PushEvent(EV_CANCEL, prev.dir, tcode, tm, prev.price, prev.sl, prev.price, prev.sl, 0.0, -1, prev);
      PushRow(t, 0, 0, tcode, m_null);
      m_lastTcode = tcode;
      return;
     }
   m_lastTcode = RC_NONE;
   //--- 6) 新規判定と待機注文の新規／置き直し／取消（SPEC §7.3）
   SSetup best;
   FE_SetupClear(best);
   bool has = EvalBest(t, m_cons, best);
   m_lastBuy = m_evl[0];
   m_lastSell = m_evl[1];
   m_lastEvalBar = t;
   int action = 0;                                       // 1=ARMED 2=UPDATE 3=INVALID
   if(!has)
     {
      if(m_pendActive)
         action = 3;
     }
   else
      if(!m_pendActive || m_pend.dir != best.dir || m_pend.key_idx != best.key_idx)
         action = 1;
      else
         action = 2;
   for(int i = 0; i < m_nevl; i++)
     {
      int code = m_evl[i].code;
      if(code == RC_OK)
         code = (i == m_bestIdx) ? ((action == 1) ? RC_ARMED : RC_UPDATE) : RC_LOSE;
      PushRow(t, m_evl[i].dir, m_evl[i].pattern, code, m_evl[i]);
     }
   bool zb = IsZone(m_evl[0]);
   bool zs = IsZone(m_evl[1]);
   if(zb && !m_zoneBuy)
      PushEvent(EV_ZONE, 1, m_evl[0].code, tm, 0.0, 0.0, 0.0, 0.0, 0.0, -1, m_evl[0]);
   if(zs && !m_zoneSell)
      PushEvent(EV_ZONE, -1, m_evl[1].code, tm, 0.0, 0.0, 0.0, 0.0, 0.0, -1, m_evl[1]);
   m_zoneBuy = zb;
   m_zoneSell = zs;
   if(action == 3)
     {
      int ic = InvalidCode(m_pend.dir, m_pend.pattern);
      PushEvent(EV_INVALID, m_pend.dir, ic, tm, m_pend.price, m_pend.sl, m_pend.price, m_pend.sl, 0.0, -1, m_pend);
      m_pendActive = false;
     }
   else
      if(action == 1)
        {
         bool repl = m_pendActive;
         PushEvent(EV_ARMED, best.dir, repl ? 1 : 0, tm, best.price, best.sl, repl ? m_pend.price : 0.0,
                   repl ? m_pend.sl : 0.0, 0.0, -1, best);
         m_pend = best;
         m_pendActive = true;
        }
      else
         if(action == 2)
           {
            PushEvent(EV_UPDATE, best.dir, 0, tm, best.price, best.sl, m_pend.price, m_pend.sl, 0.0, -1, best);
            m_pend = best;                               // 同じ key：価格・SL を置き直す
           }
  }

//--- 建玉を1本の足で処理（fusion/broker.py の process_bar。TP なし）
void CFusionEngine::ProcessBarPos(const int t, const bool entryBar)
  {
   if(!m_pos.active)
      return;
   int d = m_pos.dir;
   double s2 = m_p.s_nom / 2;
   double o_x = m_O[t] - d * s2;
   double fav = (d == 1) ? (m_H[t] - s2) : (m_L[t] + s2);
   double adv = (d == 1) ? (m_L[t] - s2) : (m_H[t] + s2);
   double risk = MathAbs(m_pos.entry - m_pos.init_sl);
   if(risk > 0.0)
     {
      m_pos.mfe_r = MathMax(m_pos.mfe_r, (fav - m_pos.entry) * d / risk);
      m_pos.mae_r = MathMin(m_pos.mae_r, (adv - m_pos.entry) * d / risk);
     }
   if(!entryBar)
     {
      if((o_x - m_pos.sl) * d <= 0)
        {
         ClosePos(m_T[t], o_x, XR_SLGAP);                // 寄り付きが損切りを越えた
         return;
        }
     }
   if((adv - m_pos.sl) * d <= 0)
     {
      ClosePos(m_T[t], m_pos.sl, (m_pos.sl == m_pos.init_sl) ? XR_SL : XR_TRAIL);
      return;
     }
   m_pos.bars_held++;
  }

void CFusionEngine::ClosePos(const datetime tm, const double price, const int reason)
  {
   if(!m_pos.active)
      return;
   int d = m_pos.dir;
   double risk = MathAbs(m_pos.entry - m_pos.init_sl);
   double r = (risk > 0.0) ? (price - m_pos.entry) * d / risk : 0.0;
   if(ArraySize(m_trades) <= m_ntrades)
      ArrayResize(m_trades, m_ntrades + 256);
   m_trades[m_ntrades].entry_time = m_pos.entry_time;
   m_trades[m_ntrades].exit_time = tm;
   m_trades[m_ntrades].key_time = m_pos.s.key_time;
   m_trades[m_ntrades].dir = d;
   m_trades[m_ntrades].pattern = m_pos.s.pattern;
   m_trades[m_ntrades].score = m_pos.s.score;
   m_trades[m_ntrades].bars_held = m_pos.bars_held;
   m_trades[m_ntrades].reason = reason;
   m_trades[m_ntrades].phase = m_phase;
   m_trades[m_ntrades].entry = m_pos.entry;
   m_trades[m_ntrades].init_sl = m_pos.init_sl;
   m_trades[m_ntrades].exit_price = price;
   m_trades[m_ntrades].r = r;
   m_trades[m_ntrades].mfe_r = m_pos.mfe_r;
   m_trades[m_ntrades].mae_r = m_pos.mae_r;
   m_ntrades++;
   m_pos.active = false;
   PushEvent(EV_EXIT, d, reason, tm, price, m_pos.sl, m_pos.entry, m_pos.init_sl, r, m_ntrades - 1, m_pos.s);
  }

//--- 停止時：残りの仮想建玉を最後の確定足の終値で 'END' 決済（run_h1 の最後と同じ）
void CFusionEngine::CloseAtEnd(void)
  {
   if(!m_pos.active || m_n <= 0)
      return;
   ClosePos((datetime)((long)m_T[m_n - 1] + 3600), m_C[m_n - 1] - m_pos.dir * m_p.s_nom / 2, XR_END);
  }

void CFusionEngine::PushEvent(const int etype, const int dir, const int code, const datetime barTime,
                              const double price, const double sl, const double prevPrice, const double prevSl,
                              const double value, const int tradeNo, const SSetup &s)
  {
   if(ArraySize(m_ev) <= m_nev)
      ArrayResize(m_ev, m_nev + 64);
   m_ev[m_nev].etype = etype;
   m_ev[m_nev].dir = dir;
   m_ev[m_nev].code = code;
   m_ev[m_nev].phase = m_phase;
   m_ev[m_nev].trade_no = tradeNo;
   m_ev[m_nev].bar_time = barTime;
   m_ev[m_nev].price = price;
   m_ev[m_nev].sl = sl;
   m_ev[m_nev].prev_price = prevPrice;
   m_ev[m_nev].prev_sl = prevSl;
   m_ev[m_nev].value = value;
   m_ev[m_nev].s = s;
   m_nev++;
  }

void CFusionEngine::PushRow(const int t, const int dir, const int pattern, const int code, const SSetup &s)
  {
   if(ArraySize(m_rows) <= m_nrows)
      ArrayResize(m_rows, m_nrows + 1024);
   m_rows[m_nrows].bar_time = m_T[t];
   m_rows[m_nrows].dir = dir;
   m_rows[m_nrows].pattern = pattern;
   m_rows[m_nrows].code = code;
   m_rows[m_nrows].phase = m_phase;
   m_rows[m_nrows].tD1 = DowT(m_dd, t);
   m_rows[m_nrows].tBig = DowT(m_db, t);
   m_rows[m_nrows].tSmall = DowT(m_ds, t);
   m_rows[m_nrows].endBig = DowE(m_db, t);
   m_rows[m_nrows].s = s;
   m_nrows++;
  }

//--- 仮想取引の累計（回数・勝ち数・総R・現在の連敗・最大連敗）
void CFusionEngine::Stats(int &n, int &wins, double &sumR, int &curLoss, int &maxLoss) const
  {
   n = m_ntrades;
   wins = 0;
   sumR = 0.0;
   curLoss = 0;
   maxLoss = 0;
   for(int i = 0; i < m_ntrades; i++)
     {
      sumR += m_trades[i].r;
      if(m_trades[i].r > 0)
        {
         wins++;
         curLoss = 0;
        }
      else
        {
         curLoss++;
         if(curLoss > maxLoss)
            maxLoss = curLoss;
        }
     }
  }
//@@ENGINE_END

//+------------------------------------------------------------------+
//| ここから MT5 との接続（履歴・タイマー・通知・パネル・描画・発注）   |
//+------------------------------------------------------------------+
#define FUS_MIN_BARS      600      // これより少ない履歴では始めない
#define FUS_TESTER_FETCH  300      // テスターで毎時取り直す本数（履歴が変わらないため短くする）
#define FUS_PANEL_W       600
#define FUS_LINE_H        15

//--- 自動売買の実際の状態（仮想ブローカーとは別に持つ）
class CRealState
  {
public:
   CKeySet           cons;           // 実際に約定した key
   ulong             ordTicket;      // 置いている逆指値
   int               ordDir;
   int               ordKeyIdx;
   datetime          ordKeyTime;
   double            ordPrice;
   double            ordSl;
   SSetup            ordSetup;
   int               fillDir;        // 直近に出した注文（約定の検出用）
   int               fillKeyIdx;
   datetime          fillKeyTime;
   SSetup            fillSetup;
   ulong             posTicket;
   long              posId;
   int               posDir;
   datetime          posTime;
   int               posEntryIdx;
   int               posKeyIdx;
   datetime          posKeyTime;
   int               posScore;
   double            posEntry;
   double            posInitSl;
   double            posSl;
   int               closeReason;    // EA が自分で決済したときの理由（XR_*）
   bool              prevNoNew;      // 直前の足が新規停止だったか（通知の重複防止）
   int               nTrades;
   int               nWins;
   double            sumR;
   int               curLoss;
   int               maxLoss;

                     CRealState(void);
   void              Reset(void);
   void              ClearOrder(void);
   void              ClearPosition(void);
  };

CRealState::CRealState(void)
  {
   Reset();
  }

void CRealState::Reset(void)
  {
   cons.Clear();
   ClearOrder();
   ClearPosition();
   prevNoNew = false;
   fillDir = 0;
   fillKeyIdx = -1;
   fillKeyTime = 0;
   FE_SetupClear(fillSetup);
   nTrades = 0;
   nWins = 0;
   sumR = 0.0;
   curLoss = 0;
   maxLoss = 0;
  }

void CRealState::ClearOrder(void)
  {
   ordTicket = 0;
   ordDir = 0;
   ordKeyIdx = -1;
   ordKeyTime = 0;
   ordPrice = 0.0;
   ordSl = 0.0;
   FE_SetupClear(ordSetup);
  }

void CRealState::ClearPosition(void)
  {
   posTicket = 0;
   posId = 0;
   posDir = 0;
   posTime = 0;
   posEntryIdx = -1;
   posKeyIdx = -1;
   posKeyTime = 0;
   posScore = 0;
   posEntry = 0.0;
   posInitSl = 0.0;
   posSl = 0.0;
   closeReason = 0;
  }

//--- 1銘柄ぶんの状態
class CSymbolCtx
  {
public:
   string            sym;
   string            base;
   string            tag;
   CFusionEngine     eng;
   CRealState        real;
   bool              ready;
   int               tries;
   datetime          lastForming;
   int               digits;
   double            point;
   double            pip;
   int               hEval;
   int               hTrades;
   int               hReal;
   int               hBars;
   int               tradesLogged;
   int               barsLogged;
   bool              nfHas;          // 通知の重複防止（最後に通知した待機注文）
   int               nfDir;
   int               nfKey;
   double            nfPrice;
   double            nfSl;
   int               histBars;
   string            note;

                     CSymbolCtx(void);
  };

CSymbolCtx::CSymbolCtx(void)
  {
   sym = "";
   base = "";
   tag = "";
   ready = false;
   tries = 0;
   lastForming = 0;
   digits = 5;
   point = 0.00001;
   pip = 0.0001;
   hEval = INVALID_HANDLE;
   hTrades = INVALID_HANDLE;
   hReal = INVALID_HANDLE;
   hBars = INVALID_HANDLE;
   tradesLogged = 0;
   barsLogged = 0;
   nfHas = false;
   nfDir = 0;
   nfKey = -1;
   nfPrice = 0.0;
   nfSl = 0.0;
   histBars = 0;
   note = "";
  }

//+------------------------------------------------------------------+
//| グローバル                                                        |
//+------------------------------------------------------------------+
CTrade      g_trade;
CSymbolCtx *g_ctx[];
int         g_nctx = 0;
string      g_prefix = "FUSION_";
string      g_queue[];
int         g_nq = 0;
uint        g_lastSendMs = 0;
bool        g_tester = false;
bool        g_visual = true;          // パネル・描画を行うか（テスターの非ビジュアルでは行わない）
bool        g_panelDirty = true;
datetime    g_lastPanel = 0;
int         g_panelLines = 0;
bool        g_inCycle = false;

//+------------------------------------------------------------------+
//| 初期化                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_tester = (MQLInfoInteger(MQL_TESTER) != 0);
   g_visual = (!g_tester || MQLInfoInteger(MQL_VISUAL_MODE) != 0);
   if(InpN_BIG < 2 || InpN_SMALL < 1 || InpN_D1 < 2 || InpHistoryBars < FUS_MIN_BARS || InpTimerSeconds < 1)
     {
      Print("[FUSION] 入力が不正です（N_BIG≥2、N_SMALL≥1、N_D1≥2、InpHistoryBars≥600、InpTimerSeconds≥1）");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpHistoryBars < 8100)
      PrintFormat("[FUSION] 注意: InpHistoryBars=%d は D1 帳簿の探索範囲（8000本＋72）より短い。D1 帳簿と節目が全履歴の Python と異なりうる", InpHistoryBars);
   string list[];
   int n = ParseSymbols(InpSymbols, list);
   for(int i = 0; i < n; i++)
     {
      string s = list[i];
      if(!SymbolSelect(s, true))
        {
         PrintFormat("[FUSION] 銘柄 %s を気配値表示に追加できません（名前を確認してください）", s);
         continue;
        }
      CSymbolCtx *c = new CSymbolCtx();
      c.sym = s;
      c.base = FE_SymbolBase(s);
      c.tag = FileTag(s);
      c.digits = (int)SymbolInfoInteger(s, SYMBOL_DIGITS);
      c.point = SymbolInfoDouble(s, SYMBOL_POINT);
      c.pip = (c.digits == 3 || c.digits == 5) ? c.point * 10.0 : c.point;
      if(c.pip <= 0.0)
         c.pip = 1.0;
      SFusionParams p;
      FillParams(p, c);
      c.eng.Configure(p, InpExtraClosedDays, InpExtraEarlyDays);
      ArrayResize(g_ctx, g_nctx + 1);
      g_ctx[g_nctx] = c;
      g_nctx++;
      PrintFormat("[FUSION] %s を監視（表の名前 %s、s_nom=%s、XAU暦=%s）", s, c.base,
                  DoubleToString(p.s_nom, c.digits + 1), p.is_xau ? "ON" : "OFF");
     }
   if(g_nctx == 0)
     {
      Print("[FUSION] 監視できる銘柄がありません");
      return INIT_FAILED;
     }
   g_trade.SetExpertMagicNumber((ulong)InpMagicNumber);
   g_trade.SetDeviationInPoints((ulong)((InpDeviationPoints > 0) ? InpDeviationPoints : 0));
   EventSetTimer(InpTimerSeconds);
   PrintFormat("[FUSION] FUSION-CORE v1.0 起動: %d 銘柄、%s、構成=%s。優位性は検証中（結果は fusion/RESULTS.md）",
               g_nctx, InpAutoTrade ? "自動売買 ON" : "シグナル通知のみ", ConfigName());
   if(InpAutoTrade)
      Print("[FUSION] 自動売買は、§21 の検証に合格しデモでのフォワード3か月を終えた後に限って使ってください");
   RunCycle();
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| 終了                                                              |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(CheckPointer(c) == POINTER_INVALID)
         continue;
      if(c.ready)
        {
         c.eng.CloseAtEnd();                    // 照合用：残りの仮想建玉を 'END' で閉じた行を書く
         DrainOutputs(c, false);
        }
      CloseLogs(c);
      if(CheckPointer(c) == POINTER_DYNAMIC)
         delete c;
      g_ctx[i] = NULL;
     }
   g_nctx = 0;
   ObjectsDeleteAll(0, g_prefix);
   ChartRedraw(0);
  }

void OnTimer()
  {
   RunCycle();
  }

void OnTick()
  {
   RunCycle();
  }

//+------------------------------------------------------------------+
//| 全銘柄の巡回                                                      |
//+------------------------------------------------------------------+
void RunCycle(void)
  {
   if(g_inCycle)
      return;
   g_inCycle = true;
   bool changed = false;
   for(int i = 0; i < g_nctx; i++)
      if(ProcessSymbol(g_ctx[i]))
         changed = true;
   FlushNotifications();
   if(InpShowPanel && g_visual && (changed || g_panelDirty))
      UpdatePanel();
   g_inCycle = false;
  }

//--- 1銘柄の処理。状態が変わったら true
bool ProcessSymbol(CSymbolCtx *c)
  {
   if(!c.ready)
      return InitSymbol(c);
   datetime ft = iTime(c.sym, PERIOD_H1, 0);           // 形成中の足
   if(ft <= 0)
      return false;
   if(ft == c.lastForming)
     {
      if(InpAutoTrade)
         return RealReconcile(c);
      return false;
     }
   //--- 新しい足：直近の確定足を取り直し、手元と照合してから新しい足を処理する
   int want = g_tester ? FUS_TESTER_FETCH : InpHistoryBars;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int got = CopyRates(c.sym, PERIOD_H1, 1, want, rates);
   if(got <= 0)
      return false;                                     // 履歴の読込中。次の巡回で再試行
   int res = c.eng.Sync(rates, got);
   if(res < 0)
     {
      PrintFormat("[FUSION] %s: 手元の履歴と取り直した足が食い違うため、読み込み直して再生します", c.sym);
      ResetSymbol(c);
      return InitSymbol(c);
     }
   DrainOutputs(c, true);
   //--- 形成中の足の始まり：休場明けフォールバック（1）
   double fo = iOpen(c.sym, PERIOD_H1, 0);
   bool gapNow = (c.eng.m_n > 0 && !c.eng.IsWeekendBar(ft) && ft > c.eng.m_T[c.eng.m_n - 1] &&
                  c.eng.GapBefore(c.eng.m_T[c.eng.m_n - 1], ft));
   if(fo > 0)
     {
      c.eng.PreBarForming(ft, fo);
      DrainOutputs(c, true);
     }
   if(InpAutoTrade)
     {
      RealReconcile(c);
      if(res > 0)
         RealOnBar(c, gapNow);
      if(gapNow)
         RealGapFallback(c);
     }
   c.lastForming = ft;
   if(InpDrawChart && g_visual && c.sym == _Symbol)
      DrawChart(c);
   g_panelDirty = true;
   return true;
  }

//--- 初回：履歴をそろえて読み込み、先頭から仮想で再生する
bool InitSymbol(CSymbolCtx *c)
  {
   c.tries++;
   int avail = Bars(c.sym, PERIOD_H1);
   if(avail <= 1)
     {
      if(c.tries % 12 == 1)
         PrintFormat("[FUSION] %s: H1 履歴を待っています", c.sym);
      c.note = "履歴待ち";
      return false;
     }
   int want = MathMin(InpHistoryBars, avail - 1);
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int got = CopyRates(c.sym, PERIOD_H1, 1, want, rates);
   if(got <= 0)
     {
      c.note = "履歴の読込中";
      return false;                                     // -1（読込中）なら次の巡回で再試行
     }
   bool synced = (SeriesInfoInteger(c.sym, PERIOD_H1, SERIES_SYNCHRONIZED) != 0);
   if(!g_tester && c.tries < 60 && (got < want || (!synced && got < InpHistoryBars)))
     {
      c.note = StringFormat("履歴の読込中 %d/%d", got, InpHistoryBars);
      return false;                                     // 最大で約 60 巡回ぶん待つ
     }
   if(got < FUS_MIN_BARS)
     {
      c.note = StringFormat("履歴不足 %d本", got);
      if(c.tries % 12 == 1)
         PrintFormat("[FUSION] %s: H1 の履歴が %d 本しかありません（%d 本以上が必要。推奨 %d 本）", c.sym, got, FUS_MIN_BARS, InpHistoryBars);
      return false;
     }
   int n = c.eng.Load(rates, got);
   c.histBars = n;
   c.note = (n < 8100) ? StringFormat("履歴%d本（推奨10000本）", n) : "";
   if(n < 8100)
      PrintFormat("[FUSION] %s: H1 の履歴が %d 本です。ツール→オプション→チャート→「チャートの最大バー数」を 10000 以上にし、履歴をダウンロードしてください", c.sym, n);
   OpenLogs(c);
   //--- 先頭から最後の確定足まで仮想で再生（通知しない）
   c.eng.m_phase = 0;
   if(c.eng.m_first >= 0)
     {
      for(int t = c.eng.m_first; t < c.eng.m_n; t++)
        {
         c.eng.PreBarIndex(t);
         c.eng.BarProcess(t);
         if(c.eng.m_nrows >= 4000)
            DrainOutputs(c, false);
        }
     }
   DrainOutputs(c, false);
   datetime ft = iTime(c.sym, PERIOD_H1, 0);
   double fo = iOpen(c.sym, PERIOD_H1, 0);
   if(ft > 0 && fo > 0)
     {
      c.eng.PreBarForming(ft, fo);
      DrainOutputs(c, false);
     }
   c.eng.m_phase = 1;
   //--- 再生の結果を「通知済み」として扱う（再起動のたびに同じ通知を出さない）
   c.nfHas = c.eng.m_pendActive;
   c.nfDir = c.eng.m_pend.dir;
   c.nfKey = c.eng.m_pend.key_idx;
   c.nfPrice = c.eng.m_pend.price;
   c.nfSl = c.eng.m_pend.sl;
   c.ready = true;
   c.lastForming = ft;
   int nt = 0, w = 0, cl = 0, ml = 0;
   double sr = 0.0;
   c.eng.Stats(nt, w, sr, cl, ml);
   PrintFormat("[FUSION] %s: %d 本を読み込み、%s〜%s を再生（仮想取引 %d 回、総R %+.1f）。待機注文 %s、建玉 %s",
               c.sym, n, FE_Time(c.eng.m_T[0]), FE_Time(c.eng.m_T[n - 1]), nt, sr,
               c.eng.m_pendActive ? "あり" : "なし", c.eng.m_pos.active ? "あり" : "なし");
   if(InpAutoTrade)
     {
      RealAdopt(c);
      //--- 自動売買では、口座に残っていた逆指値を「通知済み」とする（新しく置く注文は通知する）
      c.nfHas = (c.real.ordTicket != 0);
      c.nfDir = c.real.ordDir;
      c.nfKey = c.real.ordKeyIdx;
      c.nfPrice = c.real.ordPrice;
      c.nfSl = c.real.ordSl;
      bool gapNow = (ft > 0 && !c.eng.IsWeekendBar(ft) && ft > c.eng.m_T[n - 1] && c.eng.GapBefore(c.eng.m_T[n - 1], ft));
      RealOnBar(c, gapNow);
      if(gapNow)
         RealGapFallback(c);
     }
   if(InpDrawChart && g_visual && c.sym == _Symbol)
      DrawChart(c);
   g_panelDirty = true;
   return true;
  }

void ResetSymbol(CSymbolCtx *c)
  {
   CloseLogs(c);
   c.ready = false;
   c.tries = 0;
   c.tradesLogged = 0;
   c.barsLogged = 0;
   c.lastForming = 0;
  }

//--- 判定パラメータを入力から詰める
void FillParams(SFusionParams &p, CSymbolCtx *c)
  {
   FE_DefaultParams(p);
   p.n_big = InpN_BIG;
   p.n_small = InpN_SMALL;
   p.zone_atr = InpZONE_ATR;
   p.slope_min = InpSLOPE_MIN;
   p.entry_buf_atr = InpENTRY_BUF_ATR;
   p.sl_buf_atr = InpSL_BUF_ATR;
   p.r_min_atr = InpR_MIN_ATR;
   p.r_max_atr = InpR_MAX_ATR;
   p.n_d1 = InpN_D1;
   p.tol_lv = InpTOL_LV;
   p.tol_s = InpTOL_S;
   p.cf_min_touch = InpCF_MIN_TOUCH;
   p.rr_cf = InpRR_CF;
   p.gap_hi = InpGAP_HI;
   p.lvl_max_atr = InpLVL_MAX_ATR;
   p.g3 = InpG3;
   p.d1_gate = (int)InpD1Gate;
   p.gap_gate = InpGapGate;
   p.clear_gate = InpClearGate;
   p.cf_scope = (int)InpCfScope;
   p.support_gate = InpSupportGate;
   p.sl_mode = (int)InpSlMode;
   p.p3 = InpPattern3;
   double sn = FE_NominalSpread(c.base);
   if(sn <= 0.0)
      sn = InpSpreadPointsDefault * c.point;
   p.s_nom = sn;
   p.is_xau = (c.base == "XAUUSD");
   p.server_offset_h = InpServerOffsetHours;
  }

//--- 既定構成からの差分を表示用の名前にする
string ConfigName(void)
  {
   string s = "";
   if(InpG3)
      s += "+G3";
   if(InpD1Gate == FUS_D1_STRICT)
      s += "+d1";
   if(InpD1Gate == FUS_D1_SOFT)
      s += "+d1soft";
   if(InpGapGate)
      s += "+gap";
   if(InpClearGate)
      s += (InpCfScope == FUS_CF_DAILY) ? "+clear_d1" : "+clear";
   if(InpSupportGate)
      s += "+support";
   if(InpSlMode == FUS_SL_NODE)
      s += "+slnode";
   if(InpPattern3)
      s += "+p3";
   bool core = (InpN_BIG == 12 && InpN_SMALL == 3 && InpZONE_ATR == 0.5 && InpSLOPE_MIN == 0.0 && InpENTRY_BUF_ATR == 0.05 &&
                InpSL_BUF_ATR == 0.2 && InpR_MIN_ATR == 0.8 && InpR_MAX_ATR == 3.0);
   if(!core)
      s += "（核心パラメータ変更）";
   if(StringLen(s) == 0)
      return "fusion（既定）";
   return "F" + s;
  }

//--- "EURUSD, GBPUSD.a" → 配列
int ParseSymbols(const string text, string &out[])
  {
   ArrayResize(out, 0);
   string s = text;
   StringReplace(s, ";", ",");
   string parts[];
   int n = StringSplit(s, StringGetCharacter(",", 0), parts);
   int cnt = 0;
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringTrimLeft(p);
      StringTrimRight(p);
      if(StringLen(p) == 0)
         continue;
      bool dup = false;
      for(int j = 0; j < cnt; j++)
         if(out[j] == p)
            dup = true;
      if(dup)
         continue;
      ArrayResize(out, cnt + 1);
      out[cnt] = p;
      cnt++;
     }
   if(cnt == 0)
     {
      ArrayResize(out, 1);
      out[0] = _Symbol;
      cnt = 1;
     }
   return cnt;
  }

//--- ファイル名に使えない文字を _ にする
string FileTag(const string sym)
  {
   string out = "";
   int n = StringLen(sym);
   for(int i = 0; i < n; i++)
     {
      ushort ch = StringGetCharacter(sym, i);
      bool ok = (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || ch == '.' || ch == '_' || ch == '-';
      out += ok ? ShortToString(ch) : "_";
     }
   return out;
  }

//+------------------------------------------------------------------+
//| ログ（CSV）                                                       |
//+------------------------------------------------------------------+
void OpenLogs(CSymbolCtx *c)
  {
   CloseLogs(c);
   c.tradesLogged = 0;
   if(!InpWriteLogs)
      return;
   int common = InpLogsCommon ? FILE_COMMON : 0;
   FolderCreate("FusionEA", common);
   string base = "FusionEA\\" + c.tag;
   int flags = FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | common;
   c.hEval = FileOpen(base + "_eval.csv", flags);
   if(c.hEval != INVALID_HANDLE)
      FileWriteString(c.hEval, FE_EvalHeader() + "\r\n");
   else
      PrintFormat("[FUSION] %s_eval.csv を開けません（%d）", c.tag, GetLastError());
   c.hTrades = FileOpen(base + "_trades.csv", flags);
   if(c.hTrades != INVALID_HANDLE)
      FileWriteString(c.hTrades, FE_TradeHeader() + "\r\n");
   else
      PrintFormat("[FUSION] %s_trades.csv を開けません（%d）", c.tag, GetLastError());
   if(InpAutoTrade)
     {
      c.hReal = FileOpen(base + "_real.csv", flags);
      if(c.hReal != INVALID_HANDLE)
         FileWriteString(c.hReal, "entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,key_time,score,ticket\r\n");
     }
   //--- 判定に使った足（照合で Python に同じ足を渡すため。fusion/data.load_mt5_csv で読める）
   c.barsLogged = 0;
   c.hBars = FileOpen(base + "_bars.csv", flags);
   if(c.hBars != INVALID_HANDLE)
     {
      FileWriteString(c.hBars, "Time,Open,High,Low,Close\r\n");
      WriteNewBars(c);
     }
   //--- 照合に必要な設定（最初に読み込んだ足・s_nom・時差・構成）
   int hi = FileOpen(base + "_info.csv", flags);
   if(hi != INVALID_HANDLE)
     {
      SFusionParams p;
      p = c.eng.m_p;
      FileWriteString(hi, "key,value\r\n");
      FileWriteString(hi, "ea,FX_Fusion_EA 1.00 (FUSION-CORE v1.0)\r\n");
      FileWriteString(hi, "symbol," + c.sym + "\r\nbase," + c.base + "\r\n");
      FileWriteString(hi, "s_nom," + DoubleToString(p.s_nom, 8) + "\r\nis_xau," + (p.is_xau ? "1" : "0") + "\r\n");
      FileWriteString(hi, "server_offset_h," + IntegerToString(p.server_offset_h) + "\r\n");
      FileWriteString(hi, "first_bar_time," + ((c.eng.m_n > 0) ? FE_Time(c.eng.m_T[0]) : "") + "\r\n");
      FileWriteString(hi, "first_eval_time," + ((c.eng.m_first >= 0) ? FE_Time(c.eng.m_T[c.eng.m_first]) : "") + "\r\n");
      FileWriteString(hi, "bars_loaded," + IntegerToString(c.eng.m_n) + "\r\nhistory_bars_input," + IntegerToString(InpHistoryBars) + "\r\n");
      FileWriteString(hi, "config," + ConfigName() + "\r\n");
      FileWriteString(hi, StringFormat("switches,g3=%d d1_gate=%d gap_gate=%d clear_gate=%d cf_scope=%d support_gate=%d sl_mode=%d p3=%d\r\n",
                                       p.g3 ? 1 : 0, p.d1_gate, p.gap_gate ? 1 : 0, p.clear_gate ? 1 : 0, p.cf_scope,
                                       p.support_gate ? 1 : 0, p.sl_mode, p.p3 ? 1 : 0));
      FileWriteString(hi, StringFormat("params,N_BIG=%d N_SMALL=%d ZONE_ATR=%.4f SLOPE_MIN=%.4f ENTRY_BUF_ATR=%.4f SL_BUF_ATR=%.4f R_MIN_ATR=%.4f R_MAX_ATR=%.4f N_D1=%d TOL_LV=%.4f TOL_S=%.4f CF_MIN_TOUCH=%d RR_CF=%.4f GAP_HI=%.4f LVL_MAX_ATR=%.4f\r\n",
                                       p.n_big, p.n_small, p.zone_atr, p.slope_min, p.entry_buf_atr, p.sl_buf_atr, p.r_min_atr, p.r_max_atr,
                                       p.n_d1, p.tol_lv, p.tol_s, p.cf_min_touch, p.rr_cf, p.gap_hi, p.lvl_max_atr));
      FileWriteString(hi, "extra_closed," + InpExtraClosedDays + "\r\nextra_early," + InpExtraEarlyDays + "\r\n");
      FileClose(hi);
     }
  }

//--- 手元のバッファのうち、まだ書いていない足を <銘柄>_bars.csv に足す
void WriteNewBars(CSymbolCtx *c)
  {
   if(c.hBars == INVALID_HANDLE)
      return;
   while(c.barsLogged < c.eng.m_n)
     {
      int k = c.barsLogged;
      FileWriteString(c.hBars, FE_Time(c.eng.m_T[k]) + "," + DoubleToString(c.eng.m_O[k], 10) + "," + DoubleToString(c.eng.m_H[k], 10) + "," +
                      DoubleToString(c.eng.m_L[k], 10) + "," + DoubleToString(c.eng.m_C[k], 10) + "\r\n");
      c.barsLogged++;
     }
  }

void CloseLogs(CSymbolCtx *c)
  {
   if(c.hEval != INVALID_HANDLE)
      FileClose(c.hEval);
   if(c.hTrades != INVALID_HANDLE)
      FileClose(c.hTrades);
   if(c.hReal != INVALID_HANDLE)
      FileClose(c.hReal);
   if(c.hBars != INVALID_HANDLE)
      FileClose(c.hBars);
   c.hEval = INVALID_HANDLE;
   c.hTrades = INVALID_HANDLE;
   c.hReal = INVALID_HANDLE;
   c.hBars = INVALID_HANDLE;
  }

//--- エンジンの出力（評価行・取引・イベント）を書き出し、通知する
void DrainOutputs(CSymbolCtx *c, const bool live)
  {
   if(c.hEval != INVALID_HANDLE)
      for(int i = 0; i < c.eng.m_nrows; i++)
         FileWriteString(c.hEval, FE_EvalCsv(c.eng.m_rows[i]) + "\r\n");
   c.eng.m_nrows = 0;
   while(c.tradesLogged < c.eng.m_ntrades)
     {
      if(c.hTrades != INVALID_HANDLE)
         FileWriteString(c.hTrades, FE_TradeCsv(c.eng.m_trades[c.tradesLogged]) + "\r\n");
      c.tradesLogged++;
     }
   for(int j = 0; j < c.eng.m_nev; j++)
      HandleEvent(c, c.eng.m_ev[j], live);
   c.eng.m_nev = 0;
   WriteNewBars(c);
   if(live)
     {
      if(c.hEval != INVALID_HANDLE)
         FileFlush(c.hEval);
      if(c.hTrades != INVALID_HANDLE)
         FileFlush(c.hTrades);
      if(c.hBars != INVALID_HANDLE)
         FileFlush(c.hBars);
     }
  }

//+------------------------------------------------------------------+
//| 通知（SPEC §16.2。255文字以内、送信は間隔をあけて順に）             |
//+------------------------------------------------------------------+
void Notify(const string msg)
  {
   string m = msg;
   if(StringLen(m) > 255)
      m = StringSubstr(m, 0, 255);
   Print(m);
   if(g_tester)
      return;
   if(InpAlertPopup)
      Alert(m);
   if(InpPushNotify)
     {
      ArrayResize(g_queue, g_nq + 1, 64);
      g_queue[g_nq] = m;
      g_nq++;
     }
  }

//--- SendNotification は1分に10件程度までなので、6.5秒あけて1件ずつ送る
void FlushNotifications(void)
  {
   if(g_nq <= 0)
      return;
   uint now = GetTickCount();
   if(g_lastSendMs != 0 && now - g_lastSendMs < 6500)
      return;
   if(!SendNotification(g_queue[0]))
      PrintFormat("[FUSION] プッシュ通知の送信に失敗（%d）。MT5 の設定（オプション→通知）を確認してください", GetLastError());
   for(int i = 1; i < g_nq; i++)
      g_queue[i - 1] = g_queue[i];
   g_nq--;
   ArrayResize(g_queue, g_nq, 64);
   g_lastSendMs = now;
  }

string Px(CSymbolCtx *c, const double v)
  {
   return DoubleToString(v, c.digits);
  }

string DirName(const int d)
  {
   return (d == 1) ? "買い" : "売り";
  }

string ModeTag(void)
  {
   return InpAutoTrade ? "[FUSION自動]" : "[FUSION]";
  }

string RelName(const int rel)
  {
   if(rel == 1)
      return "合致";
   if(rel == -1)
      return "逆行";
   return "中立";
  }

//--- ARMED の文面（SPEC §16.2 の例の形式）
string MsgArmed(CSymbolCtx *c, const SSetup &s, const string head)
  {
   double rp = s.R / c.pip;
   double tp1r = (s.R > 0) ? (s.tp1 - s.price) * s.dir / s.R : 0.0;
   string sup = (s.sup_mask == 0) ? "なし" : FE_SupText(s.sup_mask);
   string cf = (s.rr_cf >= 99.0) ? "なし" : StringFormat("%.1fR", s.rr_cf);
   string pat = (s.pattern == 3) ? "③" : "①";
   return StringFormat("%s %s %s %s %s%s(%d) 逆指値%s SL%s R=%.1fpips TP1目安%s(%.1fR) 支え:%s 日足:%s 反対勢力:%s",
                       ModeTag(), c.sym, DirName(s.dir), pat, head, FE_Grade(s.score), s.score, Px(c, s.price), Px(c, s.sl),
                       rp, Px(c, s.tp1), tp1r, sup, RelName(s.rel), cf);
  }

//--- 仮想側のイベント（notify=false なら通知せず、重複防止の状態だけ更新）
void HandleEvent(CSymbolCtx *c, const SFusionEvent &e, const bool notify)
  {
   if(InpAutoTrade && e.etype != EV_ZONE)
      return;                                           // 自動売買中は実注文の側で通知する
   switch(e.etype)
     {
      case EV_ARMED:
      case EV_UPDATE:
        {
         bool send = (!c.nfHas || c.nfDir != e.dir || c.nfKey != e.s.key_idx);
         if(!send && (MathAbs(e.price - c.nfPrice) > 0.2 * e.s.atr || MathAbs(e.sl - c.nfSl) > 0.2 * e.s.atr))
            send = true;                                // 同じ key は 0.2ATR を超えて動いたときだけ
         if(send)
           {
            string head = (!c.nfHas || c.nfDir != e.dir || c.nfKey != e.s.key_idx) ? "" : "修正 ";
            c.nfHas = true;
            c.nfDir = e.dir;
            c.nfKey = e.s.key_idx;
            c.nfPrice = e.price;
            c.nfSl = e.sl;
            if(notify)
               Notify(MsgArmed(c, e.s, head));
           }
         break;
        }
      case EV_INVALID:
        {
         c.nfHas = false;
         if(notify)
            Notify(StringFormat("%s %s %s 待機注文を取消 INVALID %s（%s） 逆指値%s", ModeTag(), c.sym, DirName(e.dir),
                                FE_CodeName(e.code), FE_CodeDesc(e.code), Px(c, e.price)));
         break;
        }
      case EV_CANCEL:
        {
         if(e.code != RC_T3)
            c.nfHas = false;                            // ロールオーバーの取消は毎日なので通知しない
         if(notify && e.code != RC_T3)
            Notify(StringFormat("%s %s %s 待機注文を取消（%s）", ModeTag(), c.sym, DirName(e.dir), FE_CodeDesc(e.code)));
         break;
        }
      case EV_NONEW:
        {
         if(e.code == 1)
            c.nfHas = false;
         if(notify)
           {
            int kind = (int)e.value;
            string why = (kind == 2) ? "早仕舞い日17時" :
                         ((FE_DayOfWeek((datetime)((long)e.bar_time - (long)InpServerOffsetHours * 3600)) == 5) ? "金曜20時" : "休場前日20時");
            Notify(StringFormat("%s %s 新規停止（%s）%s", ModeTag(), c.sym, why, (e.code == 1) ? " 待機注文を取消" : ""));
           }
         break;
        }
      case EV_FILLED:
        {
         c.nfHas = false;
         if(notify)
            Notify(StringFormat("%s %s %s 約定 %s（逆指値%s） SL%s R=%.1fpips key %s", ModeTag(), c.sym, DirName(e.dir),
                                Px(c, e.price), Px(c, e.prev_price), Px(c, e.sl), MathAbs(e.price - e.sl) / c.pip,
                                FE_Time(e.s.key_time)));
         break;
        }
      case EV_TRAIL:
        {
         if(notify)
            Notify(StringFormat("%s %s %s SL引上げ %s→%s（4H%s %s）", ModeTag(), c.sym, DirName(e.dir), Px(c, e.prev_price),
                                Px(c, e.price), (e.dir == 1) ? "押し安値" : "戻り高値", Px(c, e.prev_sl)));
         break;
        }
      case EV_EXIT:
        {
         if(notify)
           {
            int held = (e.trade_no >= 0 && e.trade_no < c.eng.m_ntrades) ? c.eng.m_trades[e.trade_no].bars_held : 0;
            Notify(StringFormat("%s %s %s 決済 %s %s %+.2fR（保有%d本）", ModeTag(), c.sym, DirName(e.dir),
                                FE_ReasonName(e.code), Px(c, e.price), e.value, held));
           }
         break;
        }
      case EV_GAP:
        {
         if((e.code & 1) != 0)
            c.nfHas = false;
         if(notify)
           {
            string what = "";
            if((e.code & 2) != 0 && e.trade_no >= 0 && e.trade_no < c.eng.m_ntrades)
               what = StringFormat("建玉を始値%sで決済 %+.2fR", Px(c, c.eng.m_trades[e.trade_no].exit_price), c.eng.m_trades[e.trade_no].r);
            if((e.code & 1) != 0)
               what += (StringLen(what) > 0) ? "・待機注文を取消" : "待機注文を取消";
            Notify(StringFormat("%s %s GAP_FALLBACK 休場明け（12時間以上の空き）: %s", ModeTag(), c.sym, what));
           }
         break;
        }
      case EV_ZONE:
        {
         if(notify && InpNotifyZone)
            Notify(StringFormat("%s %s %s ZONE 押しが4H MAに到達、トリガー待ち（%s %s）", ModeTag(), c.sym, DirName(e.dir),
                                FE_CodeName(e.code), FE_CodeDesc(e.code)));
         break;
        }
     }
  }

//+------------------------------------------------------------------+
//| 自動売買（InpAutoTrade=true。SPEC §16.5・§17.5）                    |
//+------------------------------------------------------------------+
string RealComment(const int dir, const datetime keyTime)
  {
   return "FC" + IntegerToString(dir) + "_" + IntegerToString((long)keyTime);
  }

bool ParseRealComment(const string cmt, int &dir, datetime &keyTime)
  {
   if(StringFind(cmt, "FC") != 0)
      return false;
   string body = StringSubstr(cmt, 2);
   string parts[];
   if(StringSplit(body, StringGetCharacter("_", 0), parts) < 2)
      return false;
   dir = (int)StringToInteger(parts[0]);
   keyTime = (datetime)StringToInteger(parts[1]);
   return ((dir == 1 || dir == -1) && keyTime > 0);
  }

string GvName(CSymbolCtx *c, const string what)
  {
   return "FUSION_" + IntegerToString(InpMagicNumber) + "_" + c.tag + "_" + what;
  }

//--- 自分の建玉（1銘柄1建玉）
bool FindPosition(const string sym, ulong &ticket)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != sym)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      ticket = tk;
      return true;
     }
   return false;
  }

ENUM_ORDER_TYPE_TIME OrderTimeType(const string sym)
  {
   long modes = SymbolInfoInteger(sym, SYMBOL_EXPIRATION_MODE);
   if((modes & SYMBOL_EXPIRATION_GTC) != 0)
      return ORDER_TIME_GTC;
   if((modes & SYMBOL_EXPIRATION_DAY) != 0)
      return ORDER_TIME_DAY;
   return ORDER_TIME_GTC;
  }

//--- ロット＝floor(残高×risk%÷(R÷tick_size×tick_value)÷lot_step)×lot_step を [min, max] に丸める
double CalcLotSize(const string sym, const double slDist)
  {
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;
   double tickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double minLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(tickSize <= 0 || tickValue <= 0 || slDist <= 0 || step <= 0)
      return 0.0;
   double perLot = (slDist / tickSize) * tickValue;
   if(perLot <= 0)
      return 0.0;
   double lots = MathFloor((riskMoney / perLot) / step) * step;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   int vd = 0;
   double s = step;
   while(s < 1.0 - 1e-9 && vd < 8)
     {
      s *= 10.0;
      vd++;
     }
   return NormalizeDouble(lots, vd);
  }

//--- 実際の注文・建玉の変化を拾う（約定・決済の検出）。変化があれば true
bool RealReconcile(CSymbolCtx *c)
  {
   bool changed = false;
   if(c.real.ordTicket != 0 && !OrderSelect(c.real.ordTicket))
     {
      c.real.ordTicket = 0;                             // 約定・取消・失効のいずれか（建玉の有無で判断）
      changed = true;
     }
   ulong tk = 0;
   if(FindPosition(c.sym, tk))
     {
      if(PositionSelectByTicket(tk))
        {
         if(c.real.posTicket != tk)
           {
            //--- 新しい約定
            c.real.posTicket = tk;
            c.real.posId = PositionGetInteger(POSITION_IDENTIFIER);
            c.real.posDir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
            c.real.posTime = (datetime)PositionGetInteger(POSITION_TIME);
            c.real.posEntry = PositionGetDouble(POSITION_PRICE_OPEN);
            c.real.posSl = PositionGetDouble(POSITION_SL);
            c.real.posInitSl = c.real.posSl;
            c.real.posEntryIdx = c.eng.IndexOfBarContaining(c.real.posTime);
            c.real.closeReason = 0;
            int kd = 0;
            datetime kt = 0;
            if(c.real.fillDir == c.real.posDir && c.real.fillKeyIdx >= 0)
              {
               c.real.posKeyIdx = c.real.fillKeyIdx;
               c.real.posKeyTime = c.real.fillKeyTime;
               c.real.posScore = c.real.fillSetup.score;
              }
            else
               if(ParseRealComment(PositionGetString(POSITION_COMMENT), kd, kt))
                 {
                  c.real.posKeyTime = kt;
                  c.real.posKeyIdx = c.eng.IndexOfTime(kt);
                 }
            if(c.real.posKeyIdx >= 0)
               c.real.cons.Add(c.real.posDir, c.real.posKeyIdx);
            GlobalVariableSet(GvName(c, "ISL"), c.real.posInitSl);
            c.real.ClearOrder();
            c.nfHas = false;
            Notify(StringFormat("%s %s %s 約定 %s SL%s R=%.1fpips key %s", ModeTag(), c.sym, DirName(c.real.posDir),
                                Px(c, c.real.posEntry), Px(c, c.real.posSl), MathAbs(c.real.posEntry - c.real.posInitSl) / c.pip,
                                FE_Time(c.real.posKeyTime)));
            changed = true;
           }
         else
            c.real.posSl = PositionGetDouble(POSITION_SL);
        }
     }
   else
      if(c.real.posTicket != 0)
        {
         //--- 決済された：決済の約定から価格・理由を拾う
         double exitPx = 0.0;
         datetime exitT = TimeCurrent();
         long dreason = -1;
         if(HistorySelectByPosition(c.real.posId))
           {
            int nd = HistoryDealsTotal();
            for(int i = 0; i < nd; i++)
              {
               ulong dt = HistoryDealGetTicket(i);
               if(dt == 0)
                  continue;
               long entryType = HistoryDealGetInteger(dt, DEAL_ENTRY);
               if(entryType == DEAL_ENTRY_OUT || entryType == DEAL_ENTRY_OUT_BY || entryType == DEAL_ENTRY_INOUT)
                 {
                  exitPx = HistoryDealGetDouble(dt, DEAL_PRICE);
                  exitT = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
                  dreason = HistoryDealGetInteger(dt, DEAL_REASON);
                 }
              }
           }
         string why = "OTHER";
         if(c.real.closeReason != 0)
            why = FE_ReasonName(c.real.closeReason);
         else
            if(dreason == DEAL_REASON_SL)
               why = (c.real.posSl == c.real.posInitSl) ? "SL" : "TRAIL";
            else
               if(dreason == DEAL_REASON_SO)
                  why = "STOPOUT";
               else
                  if(dreason == DEAL_REASON_TP)
                     why = "TP";
                  else
                     if(dreason == DEAL_REASON_CLIENT || dreason == DEAL_REASON_MOBILE || dreason == DEAL_REASON_WEB)
                        why = "MANUAL";
         double risk = MathAbs(c.real.posEntry - c.real.posInitSl);
         double r = (risk > 0 && exitPx > 0) ? (exitPx - c.real.posEntry) * c.real.posDir / risk : 0.0;
         c.real.nTrades++;
         c.real.sumR += r;
         if(r > 0)
           {
            c.real.nWins++;
            c.real.curLoss = 0;
           }
         else
           {
            c.real.curLoss++;
            if(c.real.curLoss > c.real.maxLoss)
               c.real.maxLoss = c.real.curLoss;
           }
         if(c.hReal != INVALID_HANDLE)
           {
            FileWriteString(c.hReal, FE_Time(c.real.posTime) + "," + IntegerToString(c.real.posDir) + "," +
                            DoubleToString(c.real.posEntry, 8) + "," + DoubleToString(c.real.posInitSl, 8) + "," +
                            FE_Time(exitT) + "," + why + "," + DoubleToString(r, 6) + "," + FE_Time(c.real.posKeyTime) + "," +
                            IntegerToString(c.real.posScore) + "," + IntegerToString((long)c.real.posTicket) + "\r\n");
            FileFlush(c.hReal);
           }
         Notify(StringFormat("%s %s %s 決済 %s %s %+.2fR", ModeTag(), c.sym, DirName(c.real.posDir), why, Px(c, exitPx), r));
         GlobalVariableDel(GvName(c, "ISL"));
         c.real.ClearPosition();
         changed = true;
        }
   return changed;
  }

bool RealCancelOrder(CSymbolCtx *c, const string why)
  {
   if(c.real.ordTicket == 0)
      return true;
   if(!OrderSelect(c.real.ordTicket))
     {
      c.real.ClearOrder();
      return true;
     }
   if(!g_trade.OrderDelete(c.real.ordTicket))
     {
      PrintFormat("[FUSION] %s 逆指値 #%I64u の取消に失敗（%u %s）。次の足で再試行（%s）", c.sym, c.real.ordTicket,
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription(), why);
      return false;
     }
   PrintFormat("[FUSION] %s 逆指値 #%I64u を取消（%s）", c.sym, c.real.ordTicket, why);
   c.real.ClearOrder();
   return true;
  }

//--- 新しい逆指値（Ask がすでに price 以上なら成行。§7.5）
bool RealPlaceOrder(CSymbolCtx *c, const SSetup &s)
  {
   string sym = c.sym;
   double price = NormalizeDouble(s.price, c.digits);
   double sl = NormalizeDouble(s.sl, c.digits);
   double lots = CalcLotSize(sym, MathAbs(price - sl));
   if(lots <= 0)
     {
      PrintFormat("[FUSION] %s ロットを計算できません（R=%s）", sym, DoubleToString(MathAbs(price - sl), c.digits));
      return false;
     }
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double stops = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * c.point;
   string cmt = RealComment(s.dir, s.key_time);
   g_trade.SetTypeFillingBySymbol(sym);
   bool market = (s.dir == 1) ? (ask >= price) : (bid <= price);
   bool ok = false;
   if(market)
     {
      if((s.dir == 1 && bid - sl <= stops) || (s.dir == -1 && sl - ask <= stops))
        {
         PrintFormat("[FUSION] %s 成行の SL が STOPS_LEVEL の内側のため見送り。次の足で再評価", sym);
         return false;
        }
      ok = (s.dir == 1) ? g_trade.Buy(lots, sym, 0.0, sl, 0.0, cmt) : g_trade.Sell(lots, sym, 0.0, sl, 0.0, cmt);
     }
   else
     {
      if((s.dir == 1 && (price - ask <= stops || price - sl <= stops)) || (s.dir == -1 && (bid - price <= stops || sl - price <= stops)))
        {
         PrintFormat("[FUSION] %s 逆指値 %s が STOPS_LEVEL の内側のため置けません。次の足で再試行", sym, Px(c, price));
         return false;
        }
      if(s.dir == 1)
         ok = g_trade.BuyStop(lots, price, sym, sl, 0.0, OrderTimeType(sym), 0, cmt);
      else
         ok = g_trade.SellStop(lots, price, sym, sl, 0.0, OrderTimeType(sym), 0, cmt);
     }
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED && rc != TRADE_RETCODE_DONE_PARTIAL))
     {
      PrintFormat("[FUSION] %s 発注失敗（%u %s）。次の足で再試行", sym, rc, g_trade.ResultRetcodeDescription());
      return false;
     }
   c.real.fillDir = s.dir;
   c.real.fillKeyIdx = s.key_idx;
   c.real.fillKeyTime = s.key_time;
   c.real.fillSetup = s;
   if(market)
     {
      Notify(MsgArmed(c, s, "成行 "));
      RealReconcile(c);
      return true;
     }
   c.real.ordTicket = g_trade.ResultOrder();
   c.real.ordDir = s.dir;
   c.real.ordKeyIdx = s.key_idx;
   c.real.ordKeyTime = s.key_time;
   c.real.ordPrice = price;
   c.real.ordSl = sl;
   c.real.ordSetup = s;
   bool newKey = (!c.nfHas || c.nfDir != s.dir || c.nfKey != s.key_idx);
   if(newKey || MathAbs(price - c.nfPrice) > 0.2 * s.atr || MathAbs(sl - c.nfSl) > 0.2 * s.atr)
     {
      c.nfHas = true;
      c.nfDir = s.dir;
      c.nfKey = s.key_idx;
      c.nfPrice = price;
      c.nfSl = sl;
      Notify(MsgArmed(c, s, newKey ? "" : "修正 "));
     }
   else
      PrintFormat("[FUSION] %s 逆指値を置き直し %s SL%s（同じ key）", sym, Px(c, price), Px(c, sl));
   return true;
  }

//--- 同じ key：price・SL を今回の値に置き直す（OrderModify）
void RealModifyOrder(CSymbolCtx *c, const SSetup &s)
  {
   string sym = c.sym;
   double price = NormalizeDouble(s.price, c.digits);
   double sl = NormalizeDouble(s.sl, c.digits);
   c.real.ordSetup = s;
   if(price == c.real.ordPrice && sl == c.real.ordSl)
      return;
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double stops = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * c.point;
   double freeze = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL) * c.point;
   if((s.dir == 1 && ask >= price) || (s.dir == -1 && bid <= price))
     {
      //--- 新しい価格をすでに越えている：取消して成行（Python の始値約定に当たる）
      if(RealCancelOrder(c, "価格を越えたので成行へ"))
         RealPlaceOrder(c, s);
      return;
     }
   double dist = (s.dir == 1) ? price - ask : bid - price;
   double curDist = (s.dir == 1) ? c.real.ordPrice - ask : bid - c.real.ordPrice;
   if(dist <= stops || MathAbs(price - sl) <= stops || curDist <= freeze)
     {
      PrintFormat("[FUSION] %s 逆指値の修正は STOPS_LEVEL/FREEZE_LEVEL の内側のため見送り。前の注文を残して次の足で再試行", sym);
      return;
     }
   if(!g_trade.OrderModify(c.real.ordTicket, price, sl, 0.0, OrderTimeType(sym), 0, 0.0))
     {
      PrintFormat("[FUSION] %s 逆指値の修正に失敗（%u %s）。前の注文を残して次の足で再試行", sym, g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
      return;
     }
   double oldP = c.real.ordPrice;
   c.real.ordPrice = price;
   c.real.ordSl = sl;
   if(MathAbs(price - c.nfPrice) > 0.2 * s.atr || MathAbs(sl - c.nfSl) > 0.2 * s.atr)
     {
      c.nfPrice = price;
      c.nfSl = sl;
      Notify(MsgArmed(c, s, "修正 "));
     }
   else
      PrintFormat("[FUSION] %s 逆指値を修正 %s→%s", sym, Px(c, oldP), Px(c, price));
  }

bool RealClosePosition(CSymbolCtx *c, const int reason)
  {
   if(c.real.posTicket == 0)
      return true;
   c.real.closeReason = reason;
   g_trade.SetTypeFillingBySymbol(c.sym);
   if(!g_trade.PositionClose(c.real.posTicket))
     {
      PrintFormat("[FUSION] %s 建玉 #%I64u の決済に失敗（%u %s）。次の巡回で再試行", c.sym, c.real.posTicket,
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return false;
     }
   RealReconcile(c);
   return true;
  }

//--- 構造トレール（PositionModify）。new_SL < Bid − stops_level のときだけ（§17.7）
void RealTrail(CSymbolCtx *c, const int k)
  {
   double newSl = 0.0, swp = 0.0;
   if(!c.eng.TrailCandidate(k, c.real.posDir, c.real.posEntryIdx, c.real.posSl, newSl, swp))
      return;
   string sym = c.sym;
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double stops = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL) * c.point;
   if((c.real.posDir == 1 && !(newSl < bid - stops)) || (c.real.posDir == -1 && !(newSl > ask + stops)))
     {
      PrintFormat("[FUSION] %s トレール先 %s が現在値に近すぎるため見送り", sym, Px(c, newSl));
      return;
     }
   double nsl = NormalizeDouble(newSl, c.digits);
   if((nsl - c.real.posSl) * c.real.posDir <= 0)
      return;
   if(!g_trade.PositionModify(c.real.posTicket, nsl, 0.0))
     {
      PrintFormat("[FUSION] %s SL の引上げに失敗（%u %s）。次の足で再試行", sym, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return;
     }
   double old = c.real.posSl;
   c.real.posSl = nsl;
   Notify(StringFormat("%s %s %s SL引上げ %s→%s（4H%s %s）", ModeTag(), sym, DirName(c.real.posDir), Px(c, old), Px(c, nsl),
                       (c.real.posDir == 1) ? "押し安値" : "戻り高値", Px(c, swp)));
  }

//--- 足 k（最後の確定足）の確定時の実注文の管理（run_h1 の 4)〜6)）
void RealOnBar(CSymbolCtx *c, const bool gapNext)
  {
   int k = c.eng.m_n - 1;
   if(c.eng.m_first < 0 || k < c.eng.m_first)
      return;
   RealReconcile(c);
   bool no_new = false, flat = false, roll = false;
   int kind = 0;
   c.eng.TimeRules(k, no_new, flat, roll, kind);
   if(c.real.posTicket != 0)
     {
      if(flat)
         RealClosePosition(c, XR_WEEKEND);
      else
         RealTrail(c, k);
     }
   if(flat)
     {
      RealCancelOrder(c, "決済足");
      c.real.prevNoNew = no_new;
      return;
     }
   if(c.real.posTicket != 0)
     {
      c.real.prevNoNew = no_new;
      return;
     }
   bool edge = (no_new && !c.real.prevNoNew && kind >= 2);
   c.real.prevNoNew = no_new;
   if(no_new || roll)
     {
      bool had = (c.real.ordTicket != 0);
      RealCancelOrder(c, no_new ? "新規停止" : "ロールオーバー");
      if(no_new)
        {
         c.nfHas = false;                               // 週明けに置き直したら通知する
         if(edge)
           {
            datetime nyb = (datetime)((long)c.eng.m_T[k] - (long)InpServerOffsetHours * 3600);
            string why = (kind == 2) ? "早仕舞い日17時" : ((FE_DayOfWeek(nyb) == 5) ? "金曜20時" : "休場前日20時");
            Notify(StringFormat("%s %s 新規停止（%s）%s", ModeTag(), c.sym, why, had ? " 逆指値を取消" : ""));
           }
        }
      return;
     }
   if(gapNext)
      return;                                           // 直後に休場明けフォールバックで取消すので置かない
   SSetup best;
   FE_SetupClear(best);
   bool has = c.eng.EvalBest(k, c.real.cons, best);
   if(!has)
     {
      if(c.real.ordTicket != 0)
        {
         int ic = c.eng.InvalidCode(c.real.ordDir, c.real.ordSetup.pattern);
         double op = c.real.ordPrice;
         int od = c.real.ordDir;
         if(RealCancelOrder(c, "INVALID " + FE_CodeName(ic)))
           {
            c.nfHas = false;
            Notify(StringFormat("%s %s %s 待機注文を取消 INVALID %s（%s） 逆指値%s", ModeTag(), c.sym, DirName(od),
                                FE_CodeName(ic), FE_CodeDesc(ic), Px(c, op)));
           }
        }
      return;
     }
   //--- スプレッド防御：3×s_nom を超える間は武装・修正しない（取消して次の足で評価し直す）
   double spread = SymbolInfoDouble(c.sym, SYMBOL_ASK) - SymbolInfoDouble(c.sym, SYMBOL_BID);
   if(spread > 3.0 * c.eng.m_p.s_nom)
     {
      PrintFormat("[FUSION] %s スプレッド %s が 3×s_nom を超えるため、この足は武装しない", c.sym, DoubleToString(spread, c.digits));
      RealCancelOrder(c, "スプレッド拡大");
      return;
     }
   if(c.real.ordTicket != 0 && c.real.ordDir == best.dir && c.real.ordKeyIdx == best.key_idx)
      RealModifyOrder(c, best);
   else
     {
      if(c.real.ordTicket != 0 && !RealCancelOrder(c, "別の key に置き換え"))
         return;
      RealPlaceOrder(c, best);
     }
  }

//--- 休場明け：形成中の足の最初のティックで成行決済し、注文を取消す
void RealGapFallback(CSymbolCtx *c)
  {
   bool had = (c.real.ordTicket != 0 || c.real.posTicket != 0);
   RealCancelOrder(c, "休場明け");
   if(c.real.posTicket != 0)
      RealClosePosition(c, XR_GAP);
   if(had)
      Notify(StringFormat("%s %s GAP_FALLBACK 休場明け（12時間以上の空き）: 建玉・注文を整理", ModeTag(), c.sym));
  }

//--- 起動時：口座にある自分の注文・建玉・約定履歴を引き継ぐ
void RealAdopt(CSymbolCtx *c)
  {
   c.real.Reset();
   int n = c.eng.m_n;
   if(n <= 0)
      return;
   //--- 約定済み key（自分のマジックの約定履歴から）
   if(HistorySelect(c.eng.m_T[0], TimeCurrent() + 86400))
     {
      int nd = HistoryDealsTotal();
      for(int i = 0; i < nd; i++)
        {
         ulong dt = HistoryDealGetTicket(i);
         if(dt == 0)
            continue;
         if(HistoryDealGetString(dt, DEAL_SYMBOL) != c.sym)
            continue;
         if(HistoryDealGetInteger(dt, DEAL_MAGIC) != InpMagicNumber)
            continue;
         if(HistoryDealGetInteger(dt, DEAL_ENTRY) != DEAL_ENTRY_IN)
            continue;
         ulong ot = (ulong)HistoryDealGetInteger(dt, DEAL_ORDER);
         string cmt = HistoryOrderGetString(ot, ORDER_COMMENT);
         if(StringLen(cmt) == 0)
            cmt = HistoryDealGetString(dt, DEAL_COMMENT);
         int d = 0;
         datetime kt = 0;
         if(ParseRealComment(cmt, d, kt))
           {
            int ki = c.eng.IndexOfTime(kt);
            if(ki >= 0)
               c.real.cons.Add(d, ki);
           }
        }
     }
   //--- 待機注文
   for(int j = OrdersTotal() - 1; j >= 0; j--)
     {
      ulong ot2 = OrderGetTicket(j);
      if(ot2 == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != c.sym || OrderGetInteger(ORDER_MAGIC) != InpMagicNumber)
         continue;
      long otype = OrderGetInteger(ORDER_TYPE);
      if(otype != ORDER_TYPE_BUY_STOP && otype != ORDER_TYPE_SELL_STOP)
         continue;
      int d2 = 0;
      datetime kt2 = 0;
      int ki2 = -1;
      if(ParseRealComment(OrderGetString(ORDER_COMMENT), d2, kt2))
         ki2 = c.eng.IndexOfTime(kt2);
      if(c.real.ordTicket != 0 || ki2 < 0)
        {
         PrintFormat("[FUSION] %s 引き継げない逆指値 #%I64u を取消します", c.sym, ot2);
         g_trade.OrderDelete(ot2);
         continue;
        }
      c.real.ordTicket = ot2;
      c.real.ordDir = d2;
      c.real.ordKeyIdx = ki2;
      c.real.ordKeyTime = kt2;
      c.real.ordPrice = OrderGetDouble(ORDER_PRICE_OPEN);
      c.real.ordSl = OrderGetDouble(ORDER_SL);
      c.real.fillDir = d2;
      c.real.fillKeyIdx = ki2;
      c.real.fillKeyTime = kt2;
     }
   //--- 建玉
   ulong tk = 0;
   if(FindPosition(c.sym, tk) && PositionSelectByTicket(tk))
     {
      c.real.posTicket = tk;
      c.real.posId = PositionGetInteger(POSITION_IDENTIFIER);
      c.real.posDir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      c.real.posTime = (datetime)PositionGetInteger(POSITION_TIME);
      c.real.posEntry = PositionGetDouble(POSITION_PRICE_OPEN);
      c.real.posSl = PositionGetDouble(POSITION_SL);
      c.real.posInitSl = GlobalVariableCheck(GvName(c, "ISL")) ? GlobalVariableGet(GvName(c, "ISL")) : c.real.posSl;
      c.real.posEntryIdx = c.eng.IndexOfBarContaining(c.real.posTime);
      int d3 = 0;
      datetime kt3 = 0;
      if(ParseRealComment(PositionGetString(POSITION_COMMENT), d3, kt3))
        {
         c.real.posKeyTime = kt3;
         c.real.posKeyIdx = c.eng.IndexOfTime(kt3);
         if(c.real.posKeyIdx >= 0)
            c.real.cons.Add(c.real.posDir, c.real.posKeyIdx);
        }
      PrintFormat("[FUSION] %s 建玉 #%I64u を引き継ぎ（%s %s SL%s）", c.sym, tk, DirName(c.real.posDir), Px(c, c.real.posEntry), Px(c, c.real.posSl));
     }
  }

//+------------------------------------------------------------------+
//| パネル（SPEC §16.3）                                              |
//+------------------------------------------------------------------+
//--- 長い行は空白の位置で折り返して複数のラベルにする（ラベルの文字数の上限に備える）
void PanelText(int &li, const string text, const color clr)
  {
   string rest = text;
   bool first = true;
   while(StringLen(rest) > 0)
     {
      string piece = rest;
      if(StringLen(rest) > 60)
        {
         int cut = 60;
         for(int i = 60; i > 20; i--)
            if(StringGetCharacter(rest, i) == ' ')
              {
               cut = i;
               break;
              }
         piece = StringSubstr(rest, 0, cut);
         rest = StringSubstr(rest, cut);
         StringTrimLeft(rest);
        }
      else
         rest = "";
      PanelLine(li, first ? piece : "    " + piece, clr);
      li++;
      first = false;
     }
  }

void PanelLine(const int i, const string text, const color clr)
  {
   string name = g_prefix + "P" + IntegerToString(i);
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 20 + i * FUS_LINE_H);
   ObjectSetString(0, name, OBJPROP_FONT, InpPanelFont);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpPanelFontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void PanelBackground(const int lines)
  {
   string name = g_prefix + "PBG";
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
      ObjectSetInteger(0, name, OBJPROP_BGCOLOR, C'16,20,28');
      ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
      ObjectSetInteger(0, name, OBJPROP_COLOR, C'60,70,90');
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 6);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 16);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, FUS_PANEL_W);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, lines * FUS_LINE_H + 8);
  }

string Sgn(const int v)
  {
   if(v > 0)
      return "+" + IntegerToString(v);
   return IntegerToString(v);
  }

//--- 状態（IDLE/WATCH/ZONE/ARMED/FILLED/PAUSED。SPEC §15）
string StateName(CSymbolCtx *c, color &clr)
  {
   bool filled = InpAutoTrade ? (c.real.posTicket != 0) : c.eng.m_pos.active;
   bool armed = InpAutoTrade ? (c.real.ordTicket != 0) : c.eng.m_pendActive;
   clr = clrSilver;
   if(filled)
     {
      clr = clrDeepSkyBlue;
      return "FILLED";
     }
   if(armed)
     {
      clr = clrLime;
      return "ARMED";
     }
   int tc = c.eng.m_lastTcode;
   if(tc == RC_T1 || tc == RC_T2 || tc == RC_T3 || tc == RC_T5)
     {
      clr = clrOrange;
      return "PAUSED";
     }
   int g1 = c.eng.G1Dir(c.eng.m_lastBar);
   if(g1 == 0)
      return "IDLE";
   SSetup s;
   if(g1 == 1)
      s = c.eng.m_lastBuy;
   else
      s = c.eng.m_lastSell;
   if(c.eng.IsZone(s))
     {
      clr = clrYellow;
      return "ZONE";
     }
   clr = clrKhaki;
   return "WATCH";
  }

//--- G1 の向きと理由
string G1Text(CSymbolCtx *c)
  {
   int t = c.eng.m_lastBar;
   if(t < 0)
      return "G1:不明";
   int g1 = c.eng.G1Dir(t);
   if(g1 == 1)
      return "G1:UP";
   if(g1 == -1)
      return "G1:DOWN";
   int nh = c.eng.m_bb.Highs(t, 2, c.eng.m_tmpA);
   int nl = c.eng.m_bb.Lows(t, 2, c.eng.m_tmpB);
   if(nh < 2 || nl < 2)
      return "G1:NEUTRAL(スイング不足)";
   double h0 = c.eng.m_H[c.eng.m_tmpA[0]], h1 = c.eng.m_H[c.eng.m_tmpA[1]];
   double l0 = c.eng.m_L[c.eng.m_tmpB[0]], l1 = c.eng.m_L[c.eng.m_tmpB[1]];
   if(h0 > h1 && l0 > l1)
      return "G1:NEUTRAL(上昇終了:終値≤押し安値)";
   if(h0 < h1 && l0 < l1)
      return "G1:NEUTRAL(下降終了:終値≥戻り高値)";
   return "G1:NEUTRAL(高安が混在)";
  }

//--- エリア判定（±2ATR で touch 最大の節目）と直上・直下の節目
string AreaText(CSymbolCtx *c)
  {
   int t = c.eng.m_lastBar;
   if(t < 0 || FE_IsNA(c.eng.m_atr[t]))
      return "";
   int nlv = c.eng.Levels(t);
   double px = c.eng.m_C[t];
   double a = c.eng.m_atr[t];
   int best = -1;
   int up = -1, dn = -1;
   for(int i = 0; i < nlv; i++)
     {
      double p = c.eng.m_lv[i].price;
      if(MathAbs(p - px) <= 2.0 * a)
        {
         if(best < 0 || c.eng.m_lv[i].touch > c.eng.m_lv[best].touch ||
            (c.eng.m_lv[i].touch == c.eng.m_lv[best].touch && MathAbs(p - px) < MathAbs(c.eng.m_lv[best].price - px)))
            best = i;
        }
      if(p > px && (up < 0 || p < c.eng.m_lv[up].price))
         up = i;
      if(p <= px && (dn < 0 || p > c.eng.m_lv[dn].price))
         dn = i;
     }
   string area = "中立";
   if(best >= 0)
      area = (px > c.eng.m_lv[best].price) ? "買い方優勢" : "売り方優勢";
   string s = "エリア:" + area;
   if(up >= 0)
      s += " 上" + Px(c, c.eng.m_lv[up].price) + "(" + IntegerToString(c.eng.m_lv[up].touch) + ")";
   if(dn >= 0)
      s += " 下" + Px(c, c.eng.m_lv[dn].price) + "(" + IntegerToString(c.eng.m_lv[dn].touch) + ")";
   return s;
  }

void UpdatePanel(void)
  {
   int li = 0;
   PanelText(li, "FUSION-CORE v1.0（H1 単一時間足） " + (InpAutoTrade ? "自動売買ON" : "シグナル通知のみ") + " " + ConfigName(), clrGold);
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(!c.ready)
        {
         PanelText(li, c.sym + "  準備中（" + c.note + "）", clrGray);
         continue;
        }
      int t = c.eng.m_lastBar;
      color sc = clrSilver;
      string st = StateName(c, sc);
      string war = "";
      int td = c.eng.DowT(c.eng.m_dd, t), tb = c.eng.DowT(c.eng.m_db, t), ts = c.eng.DowT(c.eng.m_ds, t);
      if(td != 0 && tb == -td && c.eng.DowE(c.eng.m_db, t) == 0)
         war = " 戦争状態";
      //--- 1行目：状態・G1・ダウ状態
      PanelText(li, StringFormat("%s %s %s 日/4H/1H:%s/%s/%s END%d%s %s", c.sym, st, G1Text(c), Sgn(td), Sgn(tb), Sgn(ts),
                                   c.eng.DowE(c.eng.m_db, t), war, c.note), sc);
      //--- 2行目：G1 方向の評価値（なければ買い側）
      int g1 = c.eng.G1Dir(t);
      SSetup s;
      if(g1 == -1)
         s = c.eng.m_lastSell;
      else
         s = c.eng.m_lastBuy;
      string vals = "  ";
      if(s.stage >= 1)
         vals += StringFormat("depth%+.2f slope80%+.2f conv%.2f ", s.depth, s.slope, s.conv);
      if(s.stage >= 4 && s.gap_valid)
         vals += StringFormat("gap%+.1f ", s.gap);
      if(s.stage >= 3)
         vals += StringFormat("R/ATR%.2f ", s.r_atr);
      if(s.stage >= 7)
         vals += StringFormat("%s(%d)=%d/%d/%d/%d/%d/%d", FE_Grade(s.score), s.score, s.s1, s.s2, s.s3, s.s4, s.s5, s.s6);
      PanelText(li, vals, clrWhite);
      //--- 3行目：直近の理由コード・エリア
      string why = "  直近 買:" + FE_CodeName(c.eng.m_lastBuy.code) + " 売:" + FE_CodeName(c.eng.m_lastSell.code);
      if(c.eng.m_lastTcode != RC_NONE)
         why += " 見送り:" + FE_CodeName(c.eng.m_lastTcode) + "(" + FE_CodeDesc(c.eng.m_lastTcode) + ")";
      PanelText(li, why + " " + AreaText(c), clrSilver);
      //--- 4行目：待機注文・建玉
      string od = "  ";
      if(InpAutoTrade)
        {
         if(c.real.posTicket != 0)
            od += StringFormat("建玉:%s %s SL%s R=%.1fp", DirName(c.real.posDir), Px(c, c.real.posEntry), Px(c, c.real.posSl),
                               MathAbs(c.real.posEntry - c.real.posInitSl) / c.pip);
         else
            if(c.real.ordTicket != 0)
               od += StringFormat("注文:%s逆指値 %s SL%s TP1目安%s", DirName(c.real.ordDir), Px(c, c.real.ordPrice), Px(c, c.real.ordSl),
                                  Px(c, c.real.ordSetup.tp1));
            else
               od += "注文:なし";
         od += c.eng.m_pos.active ? " | 仮想:建玉" : (c.eng.m_pendActive ? " | 仮想:待機" : " | 仮想:なし");
        }
      else
        {
         if(c.eng.m_pos.active)
           {
            double cur = c.eng.m_C[c.eng.m_n - 1];
            double risk = MathAbs(c.eng.m_pos.entry - c.eng.m_pos.init_sl);
            double ur = (risk > 0) ? (cur - c.eng.m_pos.dir * c.eng.m_p.s_nom / 2 - c.eng.m_pos.entry) * c.eng.m_pos.dir / risk : 0.0;
            od += StringFormat("建玉:%s %s SL%s R=%.1fp 含み%+.2fR MFE%.2fR", DirName(c.eng.m_pos.dir), Px(c, c.eng.m_pos.entry),
                               Px(c, c.eng.m_pos.sl), risk / c.pip, ur, c.eng.m_pos.mfe_r);
           }
         else
            if(c.eng.m_pendActive)
              {
               SSetup p;
               p = c.eng.m_pend;
               od += StringFormat("待機:%s逆指値 %s SL%s TP1目安%s", DirName(p.dir), Px(c, p.price), Px(c, p.sl), Px(c, p.tp1));
               if(p.tp2_valid)
                  od += " TP2 " + Px(c, p.tp2);
              }
            else
               od += "待機注文・建玉なし";
        }
      PanelText(li, od, clrLightCyan);
      //--- 5行目：累計と次の暦イベント
      int nt = 0, w = 0, cl = 0, ml = 0;
      double sr = 0.0;
      c.eng.Stats(nt, w, sr, cl, ml);
      string stat = StringFormat("  仮想累計 %d回 勝率%.0f%% 総R%+.1f 連敗%d(最大%d)", nt, (nt > 0) ? 100.0 * w / nt : 0.0, sr, cl, ml);
      if(InpAutoTrade)
         stat += StringFormat(" | 実 %d回 %+.1fR", c.real.nTrades, c.real.sumR);
      datetime nf = 0;
      if(c.eng.m_n > 0)
         nf = c.eng.NextFlatClose((datetime)((long)c.eng.m_T[c.eng.m_n - 1] + 3600));
      if(nf > 0)
         stat += " 次の全決済 " + TimeToString(nf, TIME_DATE | TIME_MINUTES);
      PanelText(li, stat, clrSilver);
     }
   //--- 固定文言（SPEC §16.3）
   PanelLine(li++, "勝率は25〜30%前後、損益の中央値は−1R、利益は週末まで持った少数の取引に集中、", clrTomato);
   PanelLine(li++, "10〜20連敗は想定内。優位性は検証中。", clrTomato);
   PanelLine(li++, "裁量で分割・建値・早利確を加えると別の戦略になる", clrTomato);
   PanelBackground(li);
   for(int k = li; k < g_panelLines; k++)
      ObjectDelete(0, g_prefix + "P" + IntegerToString(k));
   g_panelLines = li;
   g_lastPanel = TimeCurrent();
   g_panelDirty = false;
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| チャート描画（チャートの銘柄だけ）                                 |
//+------------------------------------------------------------------+
void DrawHLine(const string name, const double price, const color clr, const int width, const ENUM_LINE_STYLE style, const string text)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
   ObjectSetDouble(0, name, OBJPROP_PRICE, price);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_STYLE, style);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void DrawSegment(const string name, const datetime t1, const double p1, const datetime t2, const double p2, const color clr, const int width)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   else
     {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
     }
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawChart(CSymbolCtx *c)
  {
   int n = c.eng.m_n;
   if(n < 2)
      return;
   int t = n - 1;
   string pf = g_prefix + "D_";
   ObjectsDeleteAll(0, pf);
   //--- SMA20/80/480（直近240本。1H 20MA＝青、4H 20MA 相当＝赤、日足 20MA 相当＝黄）
   int from = MathMax(1, n - 240);
   for(int k = from; k < n; k++)
     {
      string id = IntegerToString(k);
      if(!FE_IsNA(c.eng.m_ma20[k]) && !FE_IsNA(c.eng.m_ma20[k - 1]))
         DrawSegment(pf + "M20_" + id, c.eng.m_T[k - 1], c.eng.m_ma20[k - 1], c.eng.m_T[k], c.eng.m_ma20[k], clrDodgerBlue, 1);
      if(!FE_IsNA(c.eng.m_ma80[k]) && !FE_IsNA(c.eng.m_ma80[k - 1]))
         DrawSegment(pf + "M80_" + id, c.eng.m_T[k - 1], c.eng.m_ma80[k - 1], c.eng.m_T[k], c.eng.m_ma80[k], clrRed, 2);
      if(!FE_IsNA(c.eng.m_ma480[k]) && !FE_IsNA(c.eng.m_ma480[k - 1]))
         DrawSegment(pf + "M480_" + id, c.eng.m_T[k - 1], c.eng.m_ma480[k - 1], c.eng.m_T[k], c.eng.m_ma480[k], clrGold, 2);
     }
   //--- BIG スイング（直近1200本）
   int lo = n - 1200;
   for(int p = 0; p < c.eng.m_bb.m_nh; p++)
     {
      int j = c.eng.m_bb.m_hi[p];
      if(j < lo)
         continue;
      string nm = pf + "SH_" + IntegerToString(j);
      ObjectCreate(0, nm, OBJ_ARROW, 0, c.eng.m_T[j], c.eng.m_H[j]);
      ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, 234);
      ObjectSetInteger(0, nm, OBJPROP_ANCHOR, ANCHOR_BOTTOM);
      ObjectSetInteger(0, nm, OBJPROP_COLOR, clrTomato);
      ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
     }
   for(int p2 = 0; p2 < c.eng.m_bb.m_nl; p2++)
     {
      int j2 = c.eng.m_bb.m_lo[p2];
      if(j2 < lo)
         continue;
      string nm2 = pf + "SL_" + IntegerToString(j2);
      ObjectCreate(0, nm2, OBJ_ARROW, 0, c.eng.m_T[j2], c.eng.m_L[j2]);
      ObjectSetInteger(0, nm2, OBJPROP_ARROWCODE, 233);
      ObjectSetInteger(0, nm2, OBJPROP_ANCHOR, ANCHOR_TOP);
      ObjectSetInteger(0, nm2, OBJPROP_COLOR, clrDeepSkyBlue);
      ObjectSetInteger(0, nm2, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, nm2, OBJPROP_HIDDEN, true);
     }
   //--- touch 上位の節目（現在値 ±6ATR、最大8本。太さ＝強度）
   if(!FE_IsNA(c.eng.m_atr[t]))
     {
      int nlv = c.eng.Levels(t);
      double px = c.eng.m_C[t];
      double rng = 6.0 * c.eng.m_atr[t];
      bool used[];
      ArrayResize(used, nlv);
      for(int u = 0; u < nlv; u++)
         used[u] = false;
      for(int pick = 0; pick < 8; pick++)
        {
         int bi = -1;
         for(int i = 0; i < nlv; i++)
           {
            if(used[i] || MathAbs(c.eng.m_lv[i].price - px) > rng)
               continue;
            if(bi < 0 || c.eng.m_lv[i].touch > c.eng.m_lv[bi].touch)
               bi = i;
           }
         if(bi < 0)
            break;
         used[bi] = true;
         int tch = c.eng.m_lv[bi].touch;
         DrawHLine(pf + "LV_" + IntegerToString(pick), c.eng.m_lv[bi].price, (c.eng.m_lv[bi].price > px) ? clrIndianRed : clrSteelBlue,
                   MathMin(5, MathMax(1, tch)), (tch <= 1) ? STYLE_DOT : STYLE_SOLID,
                   StringFormat("節目 touch=%d 高%d安%d%s", tch, c.eng.m_lv[bi].nh, c.eng.m_lv[bi].nl, c.eng.m_lv[bi].d1 ? " 日足級" : ""));
        }
     }
   //--- 逆指値・SL・TP1/TP2 の目安線、建玉
   if(c.eng.m_pendActive)
     {
      SSetup s;
      s = c.eng.m_pend;
      DrawHLine(pf + "ORD", s.price, clrLime, 1, STYLE_DASH, "逆指値（" + DirName(s.dir) + "）");
      DrawHLine(pf + "ORDSL", s.sl, clrRed, 1, STYLE_DASH, "SL");
      DrawHLine(pf + "TP1", s.tp1, clrGold, 1, STYLE_DOT, "TP1目安（表示のみ）");
      if(s.tp2_valid)
         DrawHLine(pf + "TP2", s.tp2, clrGold, 1, STYLE_DOT, "TP2目安（表示のみ）");
     }
   if(c.eng.m_pos.active)
     {
      DrawHLine(pf + "POS", c.eng.m_pos.entry, clrWhite, 1, STYLE_SOLID, "仮想建玉（" + DirName(c.eng.m_pos.dir) + "）");
      DrawHLine(pf + "POSSL", c.eng.m_pos.sl, clrRed, 2, STYLE_SOLID, "SL（構造トレール）");
     }
   ChartRedraw(0);
  }
//+------------------------------------------------------------------+
