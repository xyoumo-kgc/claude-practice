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
//|   最終検証（未接触データで1回だけ）は不合格（fusion/RESULTS.md）。 |
//|   合格基準 P1〜P6 を一つも満たさず、v1.0 は「優位性なし」と記録  |
//|   した（7銘柄・約15年で1,609回、平均 +0.055R、95%区間 −0.049〜  |
//|   +0.163R。トレンド方向にでたらめに入る素朴なやり方と区別できな |
//|   い）。設計時の開発期間の成績は約190構成の探索による選択バイアス |
//|   を含む。前身 MinCore の審査ホールドアウトは 2010〜2012 が PF1.06、|
//|   AUDUSD・USDCAD 2013〜2017 が PF0.76。従来版EA・4P-Score も実デー |
//|   タではマイナス。SPEC §21 の「判定後の扱い」により、自動売買は無効 |
//|   （既定 OFF）のまま、シナリオ・パネル・通知の裁量の補助ツールとし |
//|   てだけ使う。改良は v1.1 として事前登録し、新しい未接触データで評価。|
//|                                                                  |
//|  【使い方】                                                       |
//|   ・どの時間足のチャートに付けてもよい。判定は常に H1 の確定足。   |
//|   ・監視銘柄は InpSymbols（カンマ区切り。空ならチャートの銘柄。    |
//|     自動売買では必須）。EURUSD.a・XAUUSDm などの接尾辞つきでよい。 |
//|     名目スプレッド s_nom は SPEC §10.3 の表から引く。表の名前は    |
//|     InpSymbolMap → 先頭6文字（GOLD〜 は XAUUSD）→ 英数字だけにして |
//|     表の名前をただ1つ含む（m.EURUSD・#XAUUSD）の順に決める。表に   |
//|     ない銘柄は InpSpreadPointsDefault ポイント。                    |
//|   ・初回に H1 の確定足を InpHistoryBars 本（既定10000。D1 帳簿が   |
//|     8000本を使うので 8100 以上）読み込み、Python と同じループを    |
//|     先頭から「仮想」で再生して、約定済み集合・待機注文・建玉を復元 |
//|     する（この間は通知しない）。足りなければサーバーから読み込ませ |
//|     て最大5分待ち、そろわなければある分で始める（8100 本未満なら、 |
//|     履歴が増えたあと休場明けに自動で読み直す）。その後は新しい確定 |
//|     足を末尾に追記し、毎時、直近の確定足を CopyRates で取り直して  |
//|     手元と照合する（食い違えば読み込み直して再生する）。           |
//|   ・新しい H1 足は OnTimer（InpTimerSeconds 秒ごと）で全銘柄を巡回 |
//|     して検出する（OnTick はチャートの銘柄でしか来ないため）。初回の |
//|     読込・読み直しはタイマーから1回に1銘柄ずつ行う。               |
//|   ・同じ口座・マジックの同じ銘柄は1つのチャートだけが監視する     |
//|     （端末のグローバル変数で監視の権利を取る。2つ目は監視しない。  |
//|     持ち主は10秒ごとに権利を確かめ、別のチャートに移っていたら、そ |
//|     の銘柄の監視・注文・決済をやめて知らせる）。                   |
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
//|     確定足ごとに「置きたい注文」を決め、実際の注文をそれに合わせる |
//|     （置けない・直せない・取消せないときは同じ足の中で再試行。間隔 |
//|     は10秒、証拠金不足・取引停止などの拒否は1分・5分、市場が閉まっ |
//|     ていたら次のティックまで）。注文が消えたら履歴で約定か取消かを |
//|     確かめ、約定なら約定済み集合に入れ、その足では新しく置かない   |
//|     （二重の建玉と、同じセットアップへの入り直しを防ぐ）。決済は建 |
//|     玉が消えるまで再試行し、失敗したらプッシュで知らせる。決済足の |
//|     終わりの2分前からは、市場が閉じる前に実建玉を決済する。切断・ |
//|     停止の間に決済足・休場明けを過ぎた建玉は、つながったらすぐ決済 |
//|     する。口座の引き継ぎ・発注は、取引サーバーにつながって10秒たっ |
//|     てから行う。                                                   |
//|                                                                  |
//|  【ログ】MQL5/Files/FusionEA/（InpLogsCommon=true なら共通フォルダ）|
//|   ストラテジーテスターでは各エージェントの砂場（Tester/Agent-*/     |
//|   MQL5/Files）に出るので、照合用に取り出すなら InpLogsCommon=true  |
//|   にする（Terminal/Common/Files/FusionEA/ に出る）。最適化中は書かない。|
//|   _eval/_trades/_bars/_info は起動・読み直しのたびに作り直す（再生 |
//|   分を含む）。前の回の4つは FusionEA/old/<銘柄>_<日時>/ に移し、   |
//|   InpLogKeep 世代まで残す。稼働中の評価行・仮想取引（phase=LIVE）は |
//|   <銘柄>_live.csv・<銘柄>_live_trades.csv にも追記する（世代が消え |
//|   ても稼働中の記録は残る。テスターでは書かない）。_real.csv と      |
//|   notify_log.csv も追記だけで、消さない。テスターの実取引は         |
//|   <銘柄>_real_tester.csv に書き、テストごとに作り直す。             |
//|   ヘッダー行つき、カンマ区切り、時刻はサーバー時間                  |
//|   "YYYY.MM.DD HH:MM"。照合ハーネス fusion/mt5_parity.py が読む:    |
//|     python -m fusion.mt5_parity --bars FusionEA/<銘柄>_bars.csv     |
//|       --trades FusionEA/<銘柄>_trades.csv                           |
//|       --eval FusionEA/<銘柄>_eval.csv --symbol <銘柄>               |
//|     （_info.csv は同じ場所から自動で読む。仮想ログは --strict 推奨）|
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
//|                        T5 決済足）。ファネルには数えない。         |
//|                        順序は run_h1 と同じ T1/T5→T2→T3→T4         |
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
//|   <銘柄>_real.csv … 自動売買の実際の取引（InpAutoTrade=true のとき。|
//|                     追記。同じ建玉は1回だけ。最適化中は書かない。   |
//|                     テスターでは <銘柄>_real_tester.csv）            |
//|    entry_time（約定の時刻）, dir, entry, initial_sl, exit_time,      |
//|    exit_reason（EA が決済したときは要求した理由 WEEKEND/GAP_FALLBACK/ |
//|    TRAIL。ほかは約定の理由 SL/TRAIL/STOPOUT/TP/MANUAL/EXPERT/OTHER、 |
//|    履歴で確かめられなければ UNKNOWN）, R, key_time, score, ticket,    |
//|    exit_price, volume, planned_entry（計画した逆指値）, slippage_pts,|
//|    profit, swap, commission, login, magic                           |
//|   <銘柄>_bars.csv … 判定に使った H1 確定足（Time,Open,High,Low,Close。|
//|                     サーバー時間のまま。換算後の土日を除いた後。      |
//|                     読込分＋以後の追記分）。fusion/data.load_mt5_csv  |
//|                     で読める。照合ではこの足を先頭から Python に渡す |
//|                     と、EA と同じ足番号になる。InpServerOffsetHours  |
//|                     が 0 でないときは、ハーネスが _info.csv の        |
//|                     server_offset_h で時刻を NY+7 に戻して回す。      |
//|   <銘柄>_info.csv … key,value（ASCII）: ea, symbol, base, s_nom,    |
//|                     is_xau, server_offset_h, first_bar_time（最初に  |
//|                     読み込んだ足）, first_eval_time（判定開始＝読込の |
//|                     93本目）, bars_loaded, history_bars_input,        |
//|                     config（fusion / F+G3 など）,                     |
//|                     core_changed, switches, params, extra_closed/early,|
//|                     login, magic, auto_trade, tester                  |
//|   <銘柄>_live.csv・<銘柄>_live_trades.csv … _eval・_trades と同じ列の|
//|                     稼働中（phase=LIVE）の行だけ。追記（END 行は書か |
//|                     ない）。テスター・最適化では書かない              |
//|   notify_log.csv  … 送った通知（UTF-8。server_time, local_time, login,|
//|                     magic, message）。テスターでは書かない            |
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
//|     週末・休場前の決済は、Python は決済足の終値、実約定は決済足の  |
//|     終わりの2分前か次の足の最初のティックの成行。                  |
//|   ・ATR14≤0 の足（14本続けて値が動かない足）は EA が R00 で見送る。 |
//|     Python は 0 割りの inf/NaN のまま評価を続けるが、MQL5 の 0 割り|
//|     は実行時エラーで EA が止まるため、意図して残している差。MT5 は |
//|     ティックのない足を作らないので、実データでは起きない。          |
//|   ・InpServerOffsetHours は固定の時差なので、夏時間の切替がずれる  |
//|     週は時刻ルールが1時間ずれうる（EA は1日1回 TimeTradeServer と  |
//|     TimeGMT から期待値を計算し、違えばパネルと通知で知らせる）。   |
//|     換算後の土日の足は捨てる（オフセット0なら fusion/data.py の    |
//|     drop_weekend と同じ）。                                         |
//|   ・照合できる構成は fusion と F+G3/F+d1/F+d1soft/F+gap/F+clear/    |
//|     F+clear_d1/F+support/F+slnode/F+p3 の9つ。ほかの事前登録の変種 |
//|     （require_hh=False・trail='small'・partial・be など）は Python 専用。|
//|                                                                  |
//|  【照合】判定エンジン部（//@@ENGINE_BEGIN〜END）は、MT5 の API を  |
//|   使わない。mt5/engine_check/run.sh がこの部分を C++ に写し、EA と |
//|   同じ流れ（読込→仮想再生→1本ずつ取り直し）で動かして、Python 参照 |
//|   実装と足ごと・方向ごとの理由コード、候補の値、取引一覧を突き合わ |
//|   せる（MetaEditor のない環境での確認用）。この部分を直したら回す。|
//|   run.sh は、MT5 接続部を含む EA 全体を C++ に写して g++ で構文と  |
//|   型も確かめる（conncheck.py。MQL5 API は conn_shim.h の代用の宣言 |
//|   なので、API の本当の引数の形は MetaEditor でしか分からない）。   |
//|   その写しを、注文・建玉・約定履歴を持つ API の模擬（conn_mock.h） |
//|   で動かし、自動売買の主なシナリオ（約定してすぐ SL、二重の記録、  |
//|   建玉2本、市場の休み、停止中の週末、一部約定、監視の権利など）も  |
//|   確かめる（conntest.cpp。模擬なので MT5 の本当の振る舞いではない）。|
//+------------------------------------------------------------------+
#property copyright   "FUSION-CORE v1.0（賢人のデイトレード × 100億円トレーダー）"
#property version     "1.01"
#property description "4H の押し目・戻り目 × 1H の転換を H1 の確定足だけで判定（仕様 fusion/SPEC.md、参照実装 fusion/strategy.py）。"
#property description "既定はシグナル通知＋パネル。最終検証は不合格で優位性は確認できなかった（fusion/RESULTS.md）。自動売買は無効のまま使う（既定 OFF）。"

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
input string InpSymbols             = "";     // 監視銘柄（カンマ区切り。空ならチャートの銘柄。自動売買では必須）
input string InpSymbolMap           = "";     // 銘柄名→表の名前（例 m.EURUSD=EURUSD;GOLD#=XAUUSD。普通は空でよい）
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
input int    InpPanelX         = 12;           // パネルの位置（左からのピクセル）
input int    InpPanelY         = 20;           // パネルの位置（上からのピクセル。ワンクリック取引を表示中は自動で下げる）
input bool   InpWriteLogs      = true;         // 評価と取引の CSV を書く（MQL5/Files/FusionEA/）
input bool   InpLogsCommon     = false;        // CSV を共通フォルダ（Terminal/Common/Files）に書く（テスターで照合するとき）
input int    InpLogKeep        = 10;           // 作り直す前のログを FusionEA/old/ に残す世代数（銘柄ごと。0 なら残さない）

input group "=== 自動売買（既定 OFF。v1.0 は最終検証で不合格のため実運用には使わない） ==="
input bool   InpAutoTrade       = false;     // 実際に逆指値を置いて売買する（InpSymbols の指定が必要）
input double InpRiskPercent     = 0.5;       // 1回のリスク（口座残高の%。0 より大きく 2 以下）
input long   InpMagicNumber     = 20261031;  // マジックナンバー（1 以上）
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
#define RC_R13      14    // 未使用（oku_only の h1_transition 用。この EA の入力にはない）
#define RC_R14      15
#define RC_R15      16
#define RC_R16      17    // 未使用（kenjin_only の target_gate 用。この EA の入力にはない）
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

//--- SPEC §10.3 の s_nom の表（銘柄名と価格単位の値）。表はここだけに書く（FE_NominalSpread と、接続部の銘柄名の判定
//    ResolveBase が使う）。fusion/broker.py の NOMINAL_SPREAD・fusion/mt5_parity.py の _TABLE_NAMES と同じであることを
//    fusion/tests/test_mt5_parity.py が確かめる
int FE_SpreadTable(string &names[], double &vals[])
  {
   ArrayResize(names, 9);
   ArrayResize(vals, 9);
   names[0] = "EURUSD";
   vals[0] = 0.00010;
   names[1] = "GBPUSD";
   vals[1] = 0.00015;
   names[2] = "USDJPY";
   vals[2] = 0.010;
   names[3] = "EURJPY";
   vals[3] = 0.015;
   names[4] = "GBPJPY";
   vals[4] = 0.025;
   names[5] = "AUDUSD";
   vals[5] = 0.00012;
   names[6] = "USDCAD";
   vals[6] = 0.00015;
   names[7] = "AUDJPY";
   vals[7] = 0.015;
   names[8] = "XAUUSD";
   vals[8] = 0.30;
   return 9;
  }

//--- SPEC §10.3 の s_nom（価格単位）。表になければ -1
double FE_NominalSpread(const string base)
  {
   string names[];
   double vals[];
   int n = FE_SpreadTable(names, vals);
   for(int i = 0; i < n; i++)
      if(names[i] == base)
         return vals[i];
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
   //--- ATR≤0 の足（14本続けて値が動かない足）は R00 にする。Python はこの条件を持たず 0 割りの inf/NaN のまま
   //    評価を続けるが、MQL5 の 0 割りは実行時エラーで EA が止まるため、意図して残している差（README の既知の差）。
   //    MT5 はティックのない足を作らないので、実データでは起きない。押しの窓・gap_prev の ATR≤0 の除外も同じ理由
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
   s.s2 = (depth <= 0) ? 15 : ((depth <= m_p.zone_atr) ? 8 : 0);   // SPEC 付録E の E-14（G2 があるので既定では 0 点は出ない）
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
   //    順序は run_h1 と同じ: 決済足 → 新規停止・ロールオーバー → 建玉あり（SPEC 付録E の E-13）
   int tcode = RC_NONE;
   if(flat)
      tcode = (kind == 1) ? RC_T1 : RC_T5;
   else
      if(no_new)
         tcode = RC_T2;
      else
         if(roll)
            tcode = RC_T3;
         else
            if(m_pos.active)
               tcode = RC_T4;
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
#define FUS_MIN_BARS        600                // これより少ない履歴では始めない
#define FUS_TESTER_FETCH    300                // テスターで毎時取り直す本数（履歴が変わらないため短くする）
#define FUS_TESTER_TIMER    60                 // テスターのタイマー間隔（秒）。チャート以外の銘柄を見るときだけ使う
#define FUS_PRECLOSE_SEC    120                // 決済足の終わりの何秒前に実建玉を決済するか（市場が閉じる前に）
#define FUS_LATE_SEC        120                // 足の始まりからこれより後の成行は、逆指値からの越え幅を確かめる
#define FUS_PANEL_MINW      360                // パネルの背景の最小の幅（ピクセル）
#define FUS_LINE_H          15                 // パネルの1行の高さの下限（ピクセル）
#define FUS_WRAP            60                 // パネルの1行の文字数（ラベルの上限 63 文字に収める）
#define FUS_ONECLICK_H      76                 // ワンクリック取引パネルを避けて下げる高さ（ピクセル）
#define FUS_RECENT_ORD      8                  // 発注した注文の記録（約定の対応づけ用）
#define FUS_RETRY_MS        ((uint)10000)      // 発注・修正・取消・決済・トレールの再試行の間隔
#define FUS_CONN_SETTLE_MS  ((uint)10000)      // 接続（再接続）から口座の引き継ぎ・発注までに待つ時間
#define FUS_CHK_WAIT_MS     ((uint)60000)      // 消えた注文の結果（約定か取消か）を履歴で待つ長さ
#define FUS_DEAL_WAIT_MS    ((uint)30000)      // 決済の約定が履歴に入るのを待つ長さ
#define FUS_HIST_WAIT_MS    ((uint)300000)     // 履歴がそろうのを待つ長さ。過ぎたらある分で始める
#define FUS_SYNC_WAIT_MS    ((uint)30000)      // 新しい足で、足の同期（SERIES_SYNCHRONIZED）を待つ長さ
#define FUS_LOG_GAP_MS      ((uint)300000)     // 同じ待ち・見送りのログを出す間隔
#define FUS_NOTIFY_GAP_MS   ((uint)6500)       // プッシュ通知の間隔（SendNotification の上限に備える）
#define FUS_NOTIFY_OLD_MS   ((uint)900000)     // これより古い通常の通知は送らずに捨てる
#define FUS_RELOCK_MS       ((uint)60000)      // 監視の権利を取り直す間隔
#define FUS_HEARTBEAT_MS    ((uint)10000)      // 監視の権利の生存記録を書く間隔
#define FUS_STALE_LOCK_SEC  60                 // 生存記録がこれより古い権利は、持ち主が止まったとみなす
#define FUS_CLOSE_WARN2_MS  ((uint)300000)     // 決済に失敗し続けたとき、もう一度知らせるまでの時間
#define FUS_BACKOFF1_MS     ((uint)60000)      // 一時的でない拒否（証拠金不足・取引停止・要求が多すぎる等）の1回目の後の再試行の間隔
#define FUS_BACKOFF2_MS     ((uint)300000)     // 同じく2回目以降の間隔
#define FUS_MKT_HOLD_MS     ((uint)1800000)    // 市場が閉まっていたとき、新しいティックが来なくても再試行するまでの長さ
#define FUS_MKT_TRIES       2                  // 1つの足で成行を試す回数の上限（受け付けた後に拒否される場合に備える）
#define FUS_RECORDED        8                  // _real.csv に記録した建玉 ID を覚える数（二重の記録を防ぐ）
#define FUS_ORPHANS         4                  // 追っていない建玉を決済したとき、約定履歴から記録するまで覚える数
#define FUS_ISL_KEEP_DAYS   30                 // 閉じたことを確かめられない初期 SL のグローバル変数を残す日数
//--- 注文の取消の結果
#define FUS_CXL_DONE        0                  // 取消した（または約定せずに消えていた）
#define FUS_CXL_FAIL        1                  // まだ残っている（あとで再試行）
#define FUS_CXL_FILLED      2                  // 約定していた（一部約定を含む）
#define FUS_CXL_UNKNOWN     3                  // 消えたが、結果がまだ履歴にない
//--- 建玉の決済の結果
#define FUS_CLOSE_DONE      0                  // この EA が決済した
#define FUS_CLOSE_GONE      1                  // 決済を送る前後に、もう建玉がなかった（SL・ストップアウトなど）
#define FUS_CLOSE_FAIL      2                  // 決済できなかった（あとで再試行）
//--- 見送りの通知の種類（同じセットアップ・同じ理由は2回目からログだけにする）
#define FUS_SKIP_LATE       1                  // 足の途中で価格が逆指値を大きく越えていた
#define FUS_SKIP_RATIO      2                  // 最小ロットでもリスクが目標の 1.5 倍を超える
#define FUS_SKIP_MARGIN     3                  // 証拠金が足りない
#define FUS_SKIP_MARKET     4                  // 成行が約定しなかった（試行の上限）
//--- 実取引のログ（<銘柄>_real.csv。テスターでは <銘柄>_real_tester.csv）の列
#define FUS_REAL_HEADER     "entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,key_time,score,ticket,exit_price,volume,planned_entry,slippage_pts,profit,swap,commission,login,magic"

bool        g_tester = false;          // ストラテジーテスターか（待ち・再試行の時計を模擬時刻にする）

//--- 待ち・再試行・ログの間引きの時計（ミリ秒）。GetTickCount は実時間なので、テスターでは模擬時刻（TimeCurrent）で数える。
//    uint の引き算は桁あふれしても差が正しく出る（49日まで）
uint NowMs(void)
  {
   if(g_tester)
      return (uint)((ulong)TimeCurrent() * 1000);
   return GetTickCount();
  }

//--- 自動売買の実際の状態（仮想ブローカーとは別に持つ）
class CRealState
  {
public:
   CKeySet           cons;           // 実際に約定した key（足番号。読み込みのたびに約定履歴から作り直す）
   bool              adopted;        // 口座の注文・建玉・約定履歴を読んだか（起動・再接続・読み直しで false）
   bool              barDue;         // 最後の確定足の管理（RealOnBar）がまだ
   datetime          gapBar;         // 休場明けの足の開始時刻（フォールバックがまだなら 0 以外）
   //--- 置きたい注文（確定足ごとの判定の結果。実際の注文をこれに合わせて置く・直す・取消す）
   bool              want;
   SSetup            wantSetup;
   string            cancelMsg;      // 取消できたら送る通知（INVALID）
   uint              tryMs;          // 最後に発注・修正・取消を試みた時刻（再試行の間隔用。0=すぐ）
   uint              tryWaitMs;      // 次の再試行までの間隔（拒否の種類で広げる）
   int               tryFails;
   int               mktTries;       // この足で成行を試した回数
   ulong             mktTicket;      // 最後に出した成行の注文番号（約定の通知に「成行」と書く）
   bool              cancelReq;      // 自分の待機注文をすべて取消す（建玉あり・決済中・休場明け）
   uint              cxlTryMs;
   uint              cxlWaitMs;
   int               cxlFails;
   //--- 市場が閉まっていた（MARKET_CLOSED）：新しいティックが来るまで（最長 FUS_MKT_HOLD_MS）注文・決済を送らない
   uint              holdMs;         // 0=待っていない
   long              holdMsc;        // そのときの最後のティックの時刻（ミリ秒）
   bool              holdNoted;      // 決済を待つことを知らせた
   uint              lastRc;         // 最後に拒否された戻りコード（再試行の間隔を決める）
   //--- 見送りの通知の重複防止（同じ方向・key・理由）
   int               skipDir;
   datetime          skipKeyTime;
   int               skipCode;
   //--- 置いている逆指値
   ulong             ordTicket;
   int               ordDir;
   datetime          ordKeyTime;
   double            ordPrice;
   double            ordSl;
   SSetup            ordSetup;
   //--- 結果を確かめる注文（消えた逆指値・出した成行）
   ulong             chkTicket;
   int               chkDir;
   datetime          chkKeyTime;
   double            chkPlanned;
   int               chkScore;
   uint              chkSinceMs;
   //--- 約定は確かめたが、建玉をまだ見ていない（約定してすぐ閉じた場合に備える）
   long              fillPosId;
   int               fillDir;
   datetime          fillKeyTime;
   double            fillPlanned;
   int               fillScore;
   uint              fillSinceMs;
   //--- 建玉
   ulong             posTicket;
   long              posId;
   int               posDir;
   datetime          posTime;
   int               posEntryIdx;
   datetime          posKeyTime;
   int               posScore;
   double            posEntry;
   double            posInitSl;
   double            posSl;
   double            posPlanned;     // 計画した約定価格（逆指値。不明なら 0）
   double            posVolume;
   uint              goneSinceMs;    // 建玉が消えて、決済の約定を待ち始めた時刻
   //--- 決済の要求（週末・休場・休場明け・トレール先の越え。建玉が消えるまで再試行）
   int               closeReq;       // XR_*（0=なし）
   int               closeReason;    // 決済を送って成功したときの理由（XR_*）
   uint              closeSinceMs;
   uint              closeTryMs;
   int               closeFails;
   uint              closeWaitMs;
   bool              closeWarned;
   bool              closeWarned2;
   //--- トレール（確定時に決めた SL。置けるまで同じ足の中で再試行）
   double            trailSl;
   double            trailSw;
   uint              trailTryMs;
   uint              trailWaitMs;
   int               trailFails;
   //--- 切断・停止の間に決済足・休場明けを過ぎていないか、次の巡回で確かめる（起動・再接続・追いつき処理の後）
   bool              missCheck;
   bool              multiWarned;    // 自分の建玉が2本以上あることを知らせた
   //--- _real.csv に記録した建玉 ID（二重の記録を防ぐ）
   long              recordedPid[FUS_RECORDED];
   int               recordedNext;
   //--- 追っていない建玉をこの EA が決済した：約定履歴から記録する
   long              orphPid[FUS_ORPHANS];
   int               orphReq[FUS_ORPHANS];
   uint              orphSinceMs[FUS_ORPHANS];
   //--- そのほか
   bool              prevNoNew;      // 直前の足が新規停止だったか（通知の重複防止）
   string            tradeNote;      // 取引できない理由（銘柄ごとのもの。パネル用。空なら取引できる）
   uint              logMs;          // 同じ見送りのログを間引く
   int               nTrades;
   int               nWins;
   double            sumR;
   int               curLoss;
   int               maxLoss;
   //--- 発注した注文（約定の対応づけ用。古いものから上書き）
   ulong             recTicket[FUS_RECENT_ORD];
   int               recDir[FUS_RECENT_ORD];
   datetime          recKeyTime[FUS_RECENT_ORD];
   double            recPlanned[FUS_RECENT_ORD];
   int               recScore[FUS_RECENT_ORD];
   int               recNext;

                     CRealState(void);
   void              Reset(void);
   void              ClearOrder(void);
   void              ClearChk(void);
   void              ClearFill(void);
   void              ClearPosition(void);
   void              SetChk(const ulong ticket, const int dir, const datetime keyTime, const double planned, const int score);
   void              Remember(const ulong ticket, const int dir, const datetime keyTime, const double planned, const int score);
   int               FindRec(const ulong ticket) const;
   bool              Recorded(const long pid) const;
   void              MarkRecorded(const long pid);
  };

CRealState::CRealState(void)
  {
   Reset();
  }

//--- 初めの状態に戻す（起動時と、監視の権利を失ったとき）
void CRealState::Reset(void)
  {
   cons.Clear();
   adopted = false;
   barDue = false;
   gapBar = 0;
   want = false;
   FE_SetupClear(wantSetup);
   cancelMsg = "";
   tryMs = 0;
   tryWaitMs = FUS_RETRY_MS;
   tryFails = 0;
   mktTries = 0;
   mktTicket = 0;
   cancelReq = false;
   cxlTryMs = 0;
   cxlWaitMs = FUS_RETRY_MS;
   cxlFails = 0;
   holdMs = 0;
   holdMsc = 0;
   holdNoted = false;
   lastRc = 0;
   skipDir = 0;
   skipKeyTime = 0;
   skipCode = 0;
   ClearOrder();
   ClearChk();
   ClearFill();
   ClearPosition();
   closeReq = 0;
   closeSinceMs = 0;
   closeTryMs = 0;
   closeFails = 0;
   closeWaitMs = FUS_RETRY_MS;
   closeWarned = false;
   closeWarned2 = false;
   trailSl = 0.0;
   trailSw = 0.0;
   trailTryMs = 0;
   trailWaitMs = FUS_RETRY_MS;
   trailFails = 0;
   missCheck = false;
   multiWarned = false;
   for(int r = 0; r < FUS_RECORDED; r++)
      recordedPid[r] = 0;
   recordedNext = 0;
   for(int o = 0; o < FUS_ORPHANS; o++)
     {
      orphPid[o] = 0;
      orphReq[o] = 0;
      orphSinceMs[o] = 0;
     }
   prevNoNew = false;
   tradeNote = "";
   logMs = 0;
   nTrades = 0;
   nWins = 0;
   sumR = 0.0;
   curLoss = 0;
   maxLoss = 0;
   for(int i = 0; i < FUS_RECENT_ORD; i++)
     {
      recTicket[i] = 0;
      recDir[i] = 0;
      recKeyTime[i] = 0;
      recPlanned[i] = 0.0;
      recScore[i] = 0;
     }
   recNext = 0;
  }

void CRealState::ClearOrder(void)
  {
   ordTicket = 0;
   ordDir = 0;
   ordKeyTime = 0;
   ordPrice = 0.0;
   ordSl = 0.0;
   FE_SetupClear(ordSetup);
  }

void CRealState::ClearChk(void)
  {
   chkTicket = 0;
   chkDir = 0;
   chkKeyTime = 0;
   chkPlanned = 0.0;
   chkScore = 0;
   chkSinceMs = 0;
  }

void CRealState::ClearFill(void)
  {
   fillPosId = 0;
   fillDir = 0;
   fillKeyTime = 0;
   fillPlanned = 0.0;
   fillScore = 0;
   fillSinceMs = 0;
  }

void CRealState::ClearPosition(void)
  {
   posTicket = 0;
   posId = 0;
   posDir = 0;
   posTime = 0;
   posEntryIdx = -1;
   posKeyTime = 0;
   posScore = 0;
   posEntry = 0.0;
   posInitSl = 0.0;
   posSl = 0.0;
   posPlanned = 0.0;
   posVolume = 0.0;
   goneSinceMs = 0;
   closeReason = 0;
   trailSl = 0.0;
   trailSw = 0.0;
   trailTryMs = 0;
  }

void CRealState::SetChk(const ulong ticket, const int dir, const datetime keyTime, const double planned, const int score)
  {
   chkTicket = ticket;
   chkDir = dir;
   chkKeyTime = keyTime;
   chkPlanned = planned;
   chkScore = score;
   chkSinceMs = NowMs();
  }

bool CRealState::Recorded(const long pid) const
  {
   if(pid == 0)
      return false;
   for(int i = 0; i < FUS_RECORDED; i++)
      if(recordedPid[i] == pid)
         return true;
   return false;
  }

void CRealState::MarkRecorded(const long pid)
  {
   if(pid == 0 || Recorded(pid))
      return;
   recordedPid[recordedNext] = pid;
   recordedNext = (recordedNext + 1) % FUS_RECORDED;
  }

void CRealState::Remember(const ulong ticket, const int dir, const datetime keyTime, const double planned, const int score)
  {
   if(ticket == 0)
      return;
   int i = FindRec(ticket);
   if(i < 0)
     {
      i = recNext;
      recNext = (recNext + 1) % FUS_RECENT_ORD;
     }
   recTicket[i] = ticket;
   recDir[i] = dir;
   recKeyTime[i] = keyTime;
   recPlanned[i] = planned;
   recScore[i] = score;
  }

int CRealState::FindRec(const ulong ticket) const
  {
   if(ticket == 0)
      return -1;
   for(int i = 0; i < FUS_RECENT_ORD; i++)
      if(recTicket[i] == ticket)
         return i;
   return -1;
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
   bool              locked;         // この銘柄の監視の権利（同じ口座・マジックの別のチャートと重ならない）
   string            lockName;
   uint              relockMs;
   int               loads;          // 読み込んだ回数（2回目からは読み直し）
   uint              initStartMs;    // 履歴待ちを始めた時刻
   uint              logMs;          // 履歴待ちのログを最後に出した時刻
   datetime          lastForming;    // 最後に処理した形成中の足の開始時刻
   datetime          lastDone;       // 最後に処理した確定足の開始時刻（パネル用）
   int               copyFails;
   uint              syncWaitMs;     // 足の同期を待ち始めた時刻
   bool              lagWarned;
   int               reloadDay;
   int               reloadsToday;
   bool              shallow;        // 推奨より短い履歴で始めた（休場明けに履歴が増えていれば読み直す）
   int               digits;
   double            point;
   double            pip;
   int               hEval;
   int               hTrades;
   int               hBars;
   int               tradesLogged;
   int               barsLogged;
   bool              nfHas;          // 通知の重複防止（最後に通知した待機注文）
   int               nfDir;
   datetime          nfKeyTime;
   double            nfPrice;
   double            nfSl;
   int               histBars;
   string            note;           // 履歴の状態（パネル用）
   string            alert;          // 一時的な問題（パネルに赤で出す）
   //--- 監視の権利の持ち主が止まったかを、生存記録が変わらないことで確かめる（自分の時計で）
   double            lockSeenHb;     // 最後に見た生存記録の値
   uint              lockSeenMs;     // その値を最初に見た時刻（0=まだ見ていない）
   uint              lockCheckMs;    // 最後に確かめた時刻
   int               lockSame;       // 生存記録が変わらなかった回数
   //--- 読み直しの前の仮想建玉（通知のみの運用で、読み直しで変わったら知らせる）
   bool              rlHas;
   bool              rlPosActive;
   int               rlPosDir;
   datetime          rlPosTime;
   double            rlPosEntry;
   double            rlPosSl;

                     CSymbolCtx(void);
  };

CSymbolCtx::CSymbolCtx(void)
  {
   sym = "";
   base = "";
   tag = "";
   ready = false;
   locked = false;
   lockName = "";
   relockMs = 0;
   loads = 0;
   initStartMs = 0;
   logMs = 0;
   lastForming = 0;
   lastDone = 0;
   copyFails = 0;
   syncWaitMs = 0;
   lagWarned = false;
   reloadDay = -1;
   reloadsToday = 0;
   shallow = false;
   digits = 5;
   point = 0.00001;
   pip = 0.0001;
   hEval = INVALID_HANDLE;
   hTrades = INVALID_HANDLE;
   hBars = INVALID_HANDLE;
   tradesLogged = 0;
   barsLogged = 0;
   nfHas = false;
   nfDir = 0;
   nfKeyTime = 0;
   nfPrice = 0.0;
   nfSl = 0.0;
   histBars = 0;
   note = "";
   alert = "";
   lockSeenHb = 0.0;
   lockSeenMs = 0;
   lockCheckMs = 0;
   lockSame = 0;
   rlHas = false;
   rlPosActive = false;
   rlPosDir = 0;
   rlPosTime = 0;
   rlPosEntry = 0.0;
   rlPosSl = 0.0;
  }

//+------------------------------------------------------------------+
//| グローバル                                                        |
//+------------------------------------------------------------------+
CTrade      g_trade;
CSymbolCtx *g_ctx[];
int         g_nctx = 0;
string      g_prefix = "FUSION_";
string      g_queue[];                // プッシュ通知の待ち行列
int         g_qPrio[];                // 1=重要（約定・決済・休場明け・要対応）
uint        g_qMs[];                  // 入れた時刻
int         g_nq = 0;
uint        g_lastSendMs = 0;
bool        g_pushWarned = false;
bool        g_optim = false;
bool        g_visual = true;          // パネル・描画を行うか（テスターの非ビジュアルでは行わない）
bool        g_logs = true;            // CSV を書くか（InpWriteLogs かつ最適化中でない）
bool        g_panelDirty = true;
int         g_panelLines = 0;         // いま作ってあるパネルの行ラベルの数
int         g_lineH = FUS_LINE_H;
string      g_plText[];               // パネルの行（組み立て中）
color       g_plClr[];
int         g_plN = 0;
bool        g_inCycle = false;
bool        g_conn = false;           // 取引サーバーとつながっているか
uint        g_connSinceMs = 0;        // つながった（つながり直した）時刻
datetime    g_lastTickTime = 0;       // OnTick の重複を捨てる（同じ秒の2回目以降）
double      g_token = 0.0;            // このチャートの EA を見分ける値（監視の権利の持ち主）
uint        g_hbMs = 0;
bool        g_foreignChecked = false; // 管理していない FUSION の注文・建玉を、接続後に1回数えたか
string      g_tradeNote = "";         // 端末・EA・口座の理由で取引できない（全銘柄に共通。空なら取引できる）
bool        g_lagConnWarned = false;  // 未接続による処理の遅れを知らせた（全銘柄で1回）
int         g_offsetDay = -1;         // 時差の点検を最後に行った日
bool        g_offsetBad = false;
string      g_offsetNote = "";

//+------------------------------------------------------------------+
//| 初期化                                                            |
//+------------------------------------------------------------------+
int OnInit()
  {
   //--- パラメータや時間足を変えたときの再初期化ではグローバル変数が残るので、ここで初期化する
   g_nctx = 0;
   ArrayResize(g_ctx, 0);
   g_nq = 0;
   ArrayResize(g_queue, 0);
   ArrayResize(g_qPrio, 0);
   ArrayResize(g_qMs, 0);
   g_lastSendMs = 0;
   g_pushWarned = false;
   g_panelDirty = true;
   g_panelLines = 0;
   g_plN = 0;
   g_inCycle = false;
   g_lastTickTime = 0;
   g_hbMs = 0;
   g_foreignChecked = false;
   g_tradeNote = "";
   g_lagConnWarned = false;
   g_offsetDay = -1;
   g_offsetBad = false;
   g_offsetNote = "";
   g_tester = (MQLInfoInteger(MQL_TESTER) != 0);
   g_optim = (MQLInfoInteger(MQL_OPTIMIZATION) != 0);
   g_visual = (!g_tester || MQLInfoInteger(MQL_VISUAL_MODE) != 0);
   g_logs = (InpWriteLogs && !g_optim);
   //--- 監視の権利の持ち主を見分ける値はチャートの ID から作る（端末の中で重ならない）。GetMicrosecondCount は
   //    「この EA の開始から」の時間なので、同時に起動した2つのチャートで同じ値になりうる
   long cid = ChartID();
   if(cid < 0)
      cid = -cid;
   if(cid != 0)
      g_token = (double)(cid % (long)1000000000000000) + 1.0;
   else
      g_token = (double)(GetMicrosecondCount() % (ulong)1000000000000) + 1.0;
   if(InpN_BIG < 2 || InpN_SMALL < 1 || InpN_D1 < 2 || InpHistoryBars < FUS_MIN_BARS || InpTimerSeconds < 1)
     {
      Print("[FUSION] 入力が不正です（N_BIG≥2、N_SMALL≥1、N_D1≥2、InpHistoryBars≥600、InpTimerSeconds≥1）");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpHistoryBars < 8100)
      PrintFormat("[FUSION] 注意: InpHistoryBars=%d は D1 帳簿の探索範囲（8000本＋72）より短い。D1 帳簿と節目が全履歴の Python と異なりうる", InpHistoryBars);
   string list[];
   int n = ParseSymbols(InpSymbols, list);
   if(InpAutoTrade)
     {
      if(InpMagicNumber <= 0)
        {
         Print("[FUSION] 自動売買では InpMagicNumber を 1 以上にしてください（0 は手動の取引と見分けられない）");
         return INIT_PARAMETERS_INCORRECT;
        }
      if(InpRiskPercent <= 0.0 || InpRiskPercent > 2.0)
        {
         Print("[FUSION] InpRiskPercent は 0 より大きく 2 以下にしてください（推奨 0.5）");
         return INIT_PARAMETERS_INCORRECT;
        }
      if(n == 0 && !g_tester)
        {
         Print("[FUSION] 自動売買では InpSymbols に監視銘柄を書いてください（空だと、チャートの銘柄を切り替えたときに元の銘柄の注文・建玉が管理から外れる）");
         return INIT_PARAMETERS_INCORRECT;
        }
     }
   if(n == 0)
     {
      ArrayResize(list, 1);
      list[0] = _Symbol;
      n = 1;
     }
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
      c.base = ResolveBase(s);
      c.tag = FileTag(s);
      c.digits = (int)SymbolInfoInteger(s, SYMBOL_DIGITS);
      c.point = SymbolInfoDouble(s, SYMBOL_POINT);
      if(c.point <= 0.0)
         c.point = (c.digits > 0) ? MathPow(10.0, -c.digits) : 1.0;   // 銘柄の情報が読めないとき（ポイントでの割り算の 0 割りを防ぐ）
      c.pip = (c.digits == 3 || c.digits == 5) ? c.point * 10.0 : c.point;
      if(c.pip <= 0.0)
         c.pip = 1.0;
      c.lockName = LockName(c);
      SFusionParams p;
      FillParams(p, c);
      c.eng.Configure(p, InpExtraClosedDays, InpExtraEarlyDays);
      ArrayResize(g_ctx, g_nctx + 1);
      g_ctx[g_nctx] = c;
      g_nctx++;
      bool inTable = (FE_NominalSpread(c.base) > 0.0);
      PrintFormat("[FUSION] %s を監視（表の名前 %s、s_nom=%s、XAU暦=%s）", s, c.base,
                  DoubleToString(p.s_nom, c.digits + 1), p.is_xau ? "ON" : "OFF");
      if(!inTable)
         PrintFormat("[FUSION] 注意: %s は s_nom の表（SPEC §10.3）にない銘柄として扱います（s_nom=%sポイント）。表の銘柄なら InpSymbolMap で対応づけてください",
                     s, DoubleToString(InpSpreadPointsDefault, 1));
     }
   if(g_nctx == 0)
     {
      Print("[FUSION] 監視できる銘柄がありません");
      return INIT_FAILED;
     }
   //--- 同じ口座・マジックで同じ銘柄を別のチャートが監視していないか（二重の発注・通知を防ぐ）
   int nlocked = 0;
   for(int j = 0; j < g_nctx; j++)
     {
      CSymbolCtx *cj = g_ctx[j];
      if(AcquireLock(cj, true))
         nlocked++;
      else
         PrintFormat("[FUSION] %s は別のチャートの FX_Fusion_EA（同じ口座・マジック）が監視中のため、ここでは監視しません", cj.sym);
     }
   if(nlocked == 0)
     {
      Print("[FUSION] すべての銘柄を別のチャートが監視中です。同じ EA を複数のチャートに付けないでください");
      return INIT_FAILED;
     }
   g_trade.SetExpertMagicNumber((ulong)InpMagicNumber);
   g_trade.SetDeviationInPoints((ulong)((InpDeviationPoints > 0) ? InpDeviationPoints : 0));
   if(InpPushNotify && !g_tester && TerminalInfoInteger(TERMINAL_NOTIFICATIONS_ENABLED) == 0)
      Print("[FUSION] 注意: 端末のプッシュ通知が有効になっていません（ツール→オプション→通知）。通知はエキスパートログと FusionEA/notify_log.csv にだけ残します");
   if(g_visual && InpShowPanel)
     {
      uint tw = 0, th = 0;
      if(TextSetFont(InpPanelFont, -10 * InpPanelFontSize, 0) && TextGetSize("あA", tw, th))   // 大きさは 1/10 ポイント（負の値）
         g_lineH = (int)MathMax(FUS_LINE_H, (int)th + 3);
     }
   //--- テスターの実取引ログ（<銘柄>_real_tester.csv）はテストごとに作り直す（ライブの _real.csv には書かない）
   if(g_tester && !g_optim && InpAutoTrade)
      for(int f = 0; f < g_nctx; f++)
        {
         CSymbolCtx *cf = g_ctx[f];
         string rn = RealLogName(cf);
         if(FileIsExist(rn, LogCommonFlag()))
            FileDelete(rn, LogCommonFlag());
        }
   //--- タイマー（テスターでチャートの銘柄だけなら OnTick で足りる）
   bool needTimer = !g_tester;
   int sec = InpTimerSeconds;
   if(g_tester)
     {
      sec = FUS_TESTER_TIMER;
      for(int k = 0; k < g_nctx; k++)
        {
         CSymbolCtx *ck = g_ctx[k];
         if(ck.sym != _Symbol)
            needTimer = true;
        }
     }
   if(needTimer && !EventSetTimer(sec))
     {
      PrintFormat("[FUSION] タイマーを設定できません（%d）", GetLastError());
      return INIT_FAILED;
     }
   PrintFormat("[FUSION] FUSION-CORE v1.0 起動: %d 銘柄、%s、構成=%s。最終検証は不合格で、優位性は確認できなかった（fusion/RESULTS.md）",
               g_nctx, InpAutoTrade ? "自動売買 ON" : "シグナル通知のみ", ConfigName());
   if(InpAutoTrade)
      Print("[FUSION] 注意: v1.0 は最終検証で不合格（優位性なし。fusion/RESULTS.md）。SPEC §21 により自動売買は無効のまま使う決まりです。デモでの動作確認以外には使わないでください");
   g_conn = (g_tester || TerminalInfoInteger(TERMINAL_CONNECTED) != 0);
   g_connSinceMs = NowMs();
   //--- 履歴の読込と再生は OnInit では行わない（最初のタイマー、テスターでは最初のティックから。OnInit を重くしない）。
   //    管理していない注文・建玉の点検と時差の点検は、取引サーバーにつながってから行う
   RunCycle(false);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| 終了                                                              |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(InpAutoTrade && !g_tester)
      WarnLeftovers(reason);
   for(int q = 0; q < g_nq; q++)
      PrintFormat("[FUSION] 未送信の通知: %s", g_queue[q]);
   g_nq = 0;
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(CheckPointer(c) == POINTER_INVALID)
         continue;
      if(c.ready)
        {
         c.eng.CloseAtEnd();                    // 照合用：残りの仮想建玉を 'END' で閉じた行を書く
         DrainOutputs(c, false, 0);
        }
      CloseLogs(c);
      ReleaseLock(c);
      if(CheckPointer(c) == POINTER_DYNAMIC)
         delete c;
      g_ctx[i] = NULL;
     }
   g_nctx = 0;
   ArrayResize(g_ctx, 0);
   ObjectsDeleteAll(0, g_prefix);
   g_panelLines = 0;
   ChartRedraw(0);
  }

void OnTimer()
  {
   RunCycle(true);
  }

void OnTick()
  {
   datetime now = TimeCurrent();
   if(now == g_lastTickTime)
      return;                                   // 同じ秒の2回目以降のティックは捨てる
   g_lastTickTime = now;
   RunCycle(g_tester);                          // 初回の読込はタイマーから（テスターではティックからも）
  }

//+------------------------------------------------------------------+
//| 全銘柄の巡回                                                      |
//+------------------------------------------------------------------+
void RunCycle(const bool fromTimer)
  {
   if(g_inCycle)
      return;
   g_inCycle = true;
   UpdateConnection();
   Heartbeats();
   //--- つながって口座の同期を待った後に1回：この EA が管理していない FUSION の注文・建玉を数えて知らせる
   if(!g_tester && !g_foreignChecked && TradeReady())
     {
      g_foreignChecked = true;
      WarnForeignOrders();
     }
   if(InpAutoTrade && TradeReady())
      CheckGlobalPermission();                  // 端末・EA・口座の理由は全銘柄で1通（銘柄ごとの理由は RealService で）
   bool changed = false;
   //--- 準備済みの銘柄を先に（新しい確定足の処理）
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(!c.locked)
        {
         if(fromTimer && TryRelock(c))
            changed = true;
         continue;
        }
      if(c.ready && ProcessSymbol(c))
         changed = true;
     }
   //--- 初回の読込・読み直しは1回に1銘柄まで（重い再生で、ほかの銘柄の新しい足や決済を待たせない）
   if(fromTimer)
      for(int j = 0; j < g_nctx; j++)
        {
         CSymbolCtx *c2 = g_ctx[j];
         if(!c2.locked || c2.ready)
            continue;
         if(InitSymbol(c2))
           {
            changed = true;
            break;
           }
        }
   //--- 自動売買（準備中・読み直し中の銘柄も、休場明け・決済・取消は続ける）
   if(InpAutoTrade)
      for(int k = 0; k < g_nctx; k++)
        {
         CSymbolCtx *c3 = g_ctx[k];
         if(c3.locked && RealService(c3))
            changed = true;
        }
   FlushNotifications();
   if(fromTimer)
      CheckServerOffset();
   if(InpShowPanel && g_visual && (changed || g_panelDirty))
      UpdatePanel();
   g_inCycle = false;
  }

//--- 取引サーバーとの接続。つながり直したら、口座の状態を読み直す
void UpdateConnection(void)
  {
   if(g_tester)
     {
      g_conn = true;
      return;
     }
   bool conn = (TerminalInfoInteger(TERMINAL_CONNECTED) != 0);
   if(conn && !g_conn)
     {
      g_connSinceMs = NowMs();
      for(int i = 0; i < g_nctx; i++)
        {
         CSymbolCtx *c = g_ctx[i];
         c.real.adopted = false;
        }
      g_offsetDay = -1;                         // 時差はつながり直すたびに点検し直す
      g_lagConnWarned = false;
      g_panelDirty = true;
     }
   if(!conn && g_conn)
      g_panelDirty = true;
   g_conn = conn;
  }

//--- 口座の引き継ぎ・発注をしてよいか（接続してから口座の同期を少し待つ）
bool TradeReady(void)
  {
   if(g_tester)
      return true;
   return (g_conn && NowMs() - g_connSinceMs >= FUS_CONN_SETTLE_MS);
  }

datetime NowServer(void)
  {
   return g_tester ? TimeCurrent() : TimeTradeServer();
  }

//--- 1銘柄の処理（準備済み）。新しい確定足を処理したら true
bool ProcessSymbol(CSymbolCtx *c)
  {
   datetime ft = iTime(c.sym, PERIOD_H1, 0);           // 形成中の足
   if(ft <= 0 || ft == c.lastForming)
      return false;
   //--- 新しい足：取引サーバーにつながっているときだけ進める（再接続の直後に欠けた足で判定しない）
   if(!g_tester && !g_conn)
     {
      CheckLag(c, ft);
      return false;
     }
   int want = g_tester ? FUS_TESTER_FETCH : InpHistoryBars;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int got = CopyRates(c.sym, PERIOD_H1, 1, want, rates);
   if(got <= 0)
     {
      c.copyFails++;
      if(c.copyFails == 12 || c.copyFails % 720 == 0)
         PrintFormat("[FUSION] %s: H1 の足を取り直せません（CopyRates=%d、%d 回目）。次の巡回で再試行", c.sym, got, c.copyFails);
      CheckLag(c, ft);
      return false;
     }
   c.copyFails = 0;
   //--- 足がまだ同期していなければ、少し（最大 FUS_SYNC_WAIT_MS）待つ。待ちきったら進める
   if(!g_tester && SeriesInfoInteger(c.sym, PERIOD_H1, SERIES_SYNCHRONIZED) == 0)
     {
      uint nowMs = NowMs();
      if(c.syncWaitMs == 0)
         c.syncWaitMs = nowMs;
      if(nowMs - c.syncWaitMs < FUS_SYNC_WAIT_MS)
        {
         CheckLag(c, ft);
         return false;
        }
     }
   c.syncWaitMs = 0;
   int res = c.eng.Sync(rates, got);
   if(res < 0)
     {
      ScheduleReload(c, "手元の履歴と取り直した足が食い違う");
      return true;
     }
   int n = c.eng.m_n;
   datetime lastT = c.eng.m_T[n - 1];
   //--- 何本かまとめて追記した（端末が止まっていた等）：最後の足より前のイベントは通知せず、1通にまとめる
   int skipped = DrainOutputs(c, true, (res > 1) ? lastT : (datetime)0);
   if(res > 1 && skipped > 0)
      Notify(StringFormat("%s %s 追いつき処理 %d 本（〜%s の確定足）。途中の通知 %d 件は省いた（ログには記録）",
                          ModeTag(), c.sym, res, FE_Time(lastT), skipped));
   //--- 形成中の足の始まり：休場明けフォールバック（1）
   bool gapNow = (!c.eng.IsWeekendBar(ft) && ft > lastT && c.eng.GapBefore(lastT, ft));
   double fo = iOpen(c.sym, PERIOD_H1, 0);
   if(fo > 0)
     {
      c.eng.PreBarForming(ft, fo);
      DrainOutputs(c, true, 0);
     }
   if(InpAutoTrade)
     {
      if(res > 0)
         c.real.barDue = true;
      if(res > 1)
         c.real.missCheck = true;               // 途中の足に決済足・休場明けがあれば、建玉を決済する
      if(gapNow)
         c.real.gapBar = ft;
     }
   c.lastForming = ft;
   if(res > 0)
      c.lastDone = lastT;
   c.alert = "";
   c.lagWarned = false;
   //--- 推奨より短い履歴で始めた銘柄は、休場明けに、読み込んだ最初の足より古い足が 500 本以上増えていれば
   //    読み直す（建玉は休場前に閉じている）
   if(c.shallow && gapNow)
     {
      datetime first = (datetime)SeriesInfoInteger(c.sym, PERIOD_H1, SERIES_FIRSTDATE);
      if(first > 0 && first < c.eng.m_T[0] && Bars(c.sym, PERIOD_H1, first, c.eng.m_T[0]) - 1 >= 500)
        {
         ScheduleReload(c, "古い履歴が増えた（読込時 " + IntegerToString(c.histBars) + " 本）");
         return true;
        }
     }
   if(InpDrawChart && g_visual && c.sym == _Symbol)
      DrawChart(c);
   g_panelDirty = true;
   return true;
  }

//--- 確定足の処理が遅れていないか（足の取り直しの失敗・同期待ちが続く）
void CheckLag(CSymbolCtx *c, const datetime ft)
  {
   if(c.lastForming <= 0 || ft <= c.lastForming)
      return;
   int lag = Bars(c.sym, PERIOD_H1, c.lastForming, ft) - 1;
   if(lag < 2)
      return;
   string why = !g_conn ? "未接続" : ((c.copyFails > 0) ? "足の取り直しに失敗" : "足の同期待ち");
   c.alert = StringFormat("確定足の処理が %d 本遅れている（%s）", lag, why);
   g_panelDirty = true;
   if(!c.lagWarned)
     {
      c.lagWarned = true;
      if(!g_conn)
        {
         //--- 未接続は全銘柄に共通なので、通知は1通にまとめる（つながり直したら次の切断でまた知らせる）
         if(!g_lagConnWarned)
           {
            g_lagConnWarned = true;
            Notify(StringFormat("%s 注意: 取引サーバーに未接続のため、確定足の処理が遅れている（%s ほか。%d 本）。つながると再開する",
                                ModeTag(), c.sym, lag), 1);
           }
        }
      else
         Notify(StringFormat("%s %s 注意: %s", ModeTag(), c.sym, c.alert), 1);
     }
  }

//--- 読み直しを予約する（次のタイマーで読み込み直して先頭から再生する）
void ScheduleReload(CSymbolCtx *c, const string why)
  {
   PrintFormat("[FUSION] %s: %s ため、読み込み直して再生します", c.sym, why);
   MqlDateTime dt;
   TimeToStruct(TimeLocal(), dt);
   int day = dt.year * 1000 + dt.day_of_year;
   if(day != c.reloadDay)
     {
      c.reloadDay = day;
      c.reloadsToday = 0;
     }
   c.reloadsToday++;
   if(c.reloadsToday == 4)
      Notify(StringFormat("%s %s 履歴の食い違いによる読み直しが今日 %d 回目。履歴を確かめてください（表示→銘柄→チャートバー）",
                          ModeTag(), c.sym, c.reloadsToday), 1);
   //--- 通知のみの運用：読み直しの前の仮想建玉を覚えておき、再生の後と違えば知らせる
   if(!InpAutoTrade && c.ready)
     {
      c.rlHas = true;
      c.rlPosActive = c.eng.m_pos.active;
      c.rlPosDir = c.eng.m_pos.dir;
      c.rlPosTime = c.eng.m_pos.entry_time;
      c.rlPosEntry = c.eng.m_pos.entry;
      c.rlPosSl = c.eng.m_pos.sl;
     }
   ResetSymbol(c);
  }

void ResetSymbol(CSymbolCtx *c)
  {
   CloseLogs(c);
   c.ready = false;
   c.initStartMs = 0;
   c.tradesLogged = 0;
   c.barsLogged = 0;
   c.lastForming = 0;
   c.real.adopted = false;                      // 足番号が変わるので、読み込み後に口座の状態を読み直す
   g_panelDirty = true;
  }

//--- 間引いたログを出してよいか
bool LogDue(uint &lastMs)
  {
   uint now = NowMs();
   if(lastMs != 0 && now - lastMs < FUS_LOG_GAP_MS)
      return false;
   lastMs = now;
   return true;
  }

//--- 手元の H1 はこれ以上増えないか（端末の「チャートの最大バー数」かサーバーの最初の足に届いた）
bool HistoryExhausted(CSymbolCtx *c, const datetime firstGot)
  {
   int maxBars = (int)TerminalInfoInteger(TERMINAL_MAXBARS);
   int bars = Bars(c.sym, PERIOD_H1);
   if(maxBars > 0 && bars >= maxBars)
      return true;
   datetime srvFirst = (datetime)SeriesInfoInteger(c.sym, PERIOD_M1, SERIES_SERVER_FIRSTDATE);
   if(srvFirst > 0 && (long)firstGot <= (long)srvFirst + 7 * 86400)
      return true;
   return false;
  }

//--- 手元より古い H1 を要求して、端末にサーバーから読み込ませる（MQL5 リファレンスの CheckLoadHistory と同じ方法）
void RequestOlderHistory(CSymbolCtx *c)
  {
   int bars = Bars(c.sym, PERIOD_H1);
   datetime tmp[];
   if(CopyTime(c.sym, PERIOD_H1, bars, 100, tmp) < 0)
      ResetLastError();                                 // まだ届いていない（次の巡回で数え直す）
  }

//--- 初回・読み直し：履歴をそろえて読み込み、先頭から仮想で再生する。読み込んだら true
bool InitSymbol(CSymbolCtx *c)
  {
   uint now = NowMs();
   if(c.initStartMs == 0)
      c.initStartMs = now;
   int avail = Bars(c.sym, PERIOD_H1);
   if(avail <= 1)
     {
      c.note = "履歴待ち";
      if(LogDue(c.logMs))
         PrintFormat("[FUSION] %s: H1 履歴を待っています", c.sym);
      return false;
     }
   //--- 手元より多く頼むと、端末がサーバーから読み込む（ただし「チャートの最大バー数」を超えては頼まない）。
   //    テスターと、待ちきった後は手元にある分だけ頼む（必ず読める範囲）
   int want = InpHistoryBars;
   int maxBars = (int)TerminalInfoInteger(TERMINAL_MAXBARS);
   if(maxBars > 1 && want > maxBars - 1)
      want = maxBars - 1;
   bool late = (now - c.initStartMs >= FUS_HIST_WAIT_MS);
   if((g_tester || late) && want > avail - 1)
      want = avail - 1;
   //--- 読み込む時点の形成中の足（再生中に次の足が始まっても、読み込んでいない確定足を次の巡回で処理するため、
   //    再生の後ではなくここで読む）
   datetime ft = iTime(c.sym, PERIOD_H1, 0);
   double fo = iOpen(c.sym, PERIOD_H1, 0);
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int got = CopyRates(c.sym, PERIOD_H1, 1, want, rates);
   if(got <= 0)
     {
      c.note = "履歴の読込中";
      return false;                                     // -1（読込中）なら次の巡回で再試行
     }
   if(!g_tester && !late && got < want && !HistoryExhausted(c, rates[0].time))
     {
      RequestOlderHistory(c);
      c.note = StringFormat("履歴の読込中 %d/%d", got, want);
      if(LogDue(c.logMs))
         PrintFormat("[FUSION] %s: H1 の履歴を読み込み中（%d/%d 本）。最大 %d 分待ちます", c.sym, got, want,
                     (int)(FUS_HIST_WAIT_MS / 60000));
      return false;
     }
   if(got < FUS_MIN_BARS)
     {
      c.note = StringFormat("履歴不足 %d本", got);
      if(LogDue(c.logMs))
         PrintFormat("[FUSION] %s: H1 の履歴が %d 本しかありません（%d 本以上が必要。推奨 %d 本）", c.sym, got, FUS_MIN_BARS, InpHistoryBars);
      return false;
     }
   int n = c.eng.Load(rates, got);
   if(n <= 0)
     {
      c.note = "有効な足なし";
      if(LogDue(c.logMs))
         PrintFormat("[FUSION] %s: 読み込んだ足がすべて土日として除かれました（InpServerOffsetHours を確認）", c.sym);
      return false;
     }
   c.histBars = n;
   c.loads++;
   c.initStartMs = 0;
   c.logMs = 0;
   c.shallow = (n < 8100 && n < InpHistoryBars);
   c.note = (n < 8100) ? StringFormat("履歴%d本（推奨10000本）", n) : "";
   if(n < 8100)
      PrintFormat("[FUSION] %s: H1 の履歴が %d 本です。ツール→オプション→チャート→「チャートの最大バー数」を 10000 以上にし、履歴をダウンロードしてください（増えたら休場明けに自動で読み直します）", c.sym, n);
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
            DrainOutputs(c, false, 0);
        }
     }
   DrainOutputs(c, false, 0);
   if(ft > 0 && fo > 0)
     {
      c.eng.PreBarForming(ft, fo);
      DrainOutputs(c, false, 0);
     }
   c.eng.m_phase = 1;
   //--- 再生の結果を「通知済み」として扱う（再起動のたびに同じ通知を出さない）。
   //    読み直しで新しく現れた待機注文・消えた待機注文は知らせる
   if(!InpAutoTrade)
     {
      bool has = c.eng.m_pendActive;
      if(c.loads > 1)
        {
         if(has && (!c.nfHas || c.nfDir != c.eng.m_pend.dir || c.nfKeyTime != c.eng.m_pend.key_time))
            Notify(MsgArmed(c, c.eng.m_pend, "読み直し "));
         else
            if(!has && c.nfHas)
               Notify(StringFormat("%s %s %s 待機注文は読み直しの結果なくなった（逆指値%s）", ModeTag(), c.sym, DirName(c.nfDir), Px(c, c.nfPrice)));
         //--- 仮想建玉も、読み直しの前と違えば知らせる（データの修正で、通知した建玉が再生では無かった・別の値で閉じた等）
         if(c.rlHas)
           {
            bool act = c.eng.m_pos.active;
            bool same = (c.rlPosActive == act);
            if(same && act)
               same = (c.rlPosDir == c.eng.m_pos.dir && c.rlPosTime == c.eng.m_pos.entry_time &&
                       MathAbs(c.rlPosEntry - c.eng.m_pos.entry) < 0.5 * c.point && MathAbs(c.rlPosSl - c.eng.m_pos.sl) < 0.5 * c.point);
            if(!same)
               Notify(StringFormat("%s %s 読み直しの結果、仮想建玉が変わった: %s → %s", ModeTag(), c.sym,
                                   VPosText(c, c.rlPosActive, c.rlPosDir, c.rlPosEntry, c.rlPosSl),
                                   VPosText(c, act, c.eng.m_pos.dir, c.eng.m_pos.entry, c.eng.m_pos.sl)), 1);
           }
        }
      c.rlHas = false;
      c.nfHas = has;
      c.nfDir = c.eng.m_pend.dir;
      c.nfKeyTime = c.eng.m_pend.key_time;
      c.nfPrice = c.eng.m_pend.price;
      c.nfSl = c.eng.m_pend.sl;
     }
   c.ready = true;
   c.lastForming = ft;
   c.lastDone = c.eng.m_T[n - 1];
   c.alert = "";
   c.lagWarned = false;
   int nt = 0, w = 0, cl = 0, ml = 0;
   double sr = 0.0;
   c.eng.Stats(nt, w, sr, cl, ml);
   PrintFormat("[FUSION] %s: %d 本を読み込み、%s〜%s を再生（仮想取引 %d 回、総R %+.1f）。待機注文 %s、建玉 %s",
               c.sym, n, FE_Time(c.eng.m_T[0]), FE_Time(c.eng.m_T[n - 1]), nt, sr,
               c.eng.m_pendActive ? "あり" : "なし", c.eng.m_pos.active ? "あり" : "なし");
   if(InpAutoTrade)
     {
      c.real.adopted = false;                   // 足番号が決まったので、口座の注文・建玉・約定履歴を読む
      c.real.barDue = true;                     // 最後の確定足の管理（置く・直す・取消す）を行う
      if(ft > 0 && !c.eng.IsWeekendBar(ft) && ft > c.eng.m_T[n - 1] && c.eng.GapBefore(c.eng.m_T[n - 1], ft))
         c.real.gapBar = ft;
      //--- 新規停止の通知の重複防止：次に処理する足（最後の確定足）の1本前の状態から始める
      c.real.prevNoNew = false;
      if(n >= 2)
        {
         bool nn = false, fl = false, rl = false;
         int kd = 0;
         c.eng.TimeRules(n - 2, nn, fl, rl, kd);
         c.real.prevNoNew = nn;
        }
     }
   if(InpDrawChart && g_visual && c.sym == _Symbol)
      DrawChart(c);
   g_panelDirty = true;
   return true;
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

//--- 既定構成からの差分（任意ゲートの部分。ASCII）
string ConfigSuffix(void)
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
   return s;
  }

bool CoreChanged(void)
  {
   return !(InpN_BIG == 12 && InpN_SMALL == 3 && InpZONE_ATR == 0.5 && InpSLOPE_MIN == 0.0 && InpENTRY_BUF_ATR == 0.05 &&
            InpSL_BUF_ATR == 0.2 && InpR_MIN_ATR == 0.8 && InpR_MAX_ATR == 3.0);
  }

//--- 構成名（_info.csv 用。ASCII だけ）
string ConfigTag(void)
  {
   string s = ConfigSuffix();
   return (StringLen(s) == 0) ? "fusion" : "F" + s;
  }

//--- 構成名（表示用）
string ConfigName(void)
  {
   string s = ConfigSuffix();
   if(CoreChanged())
      s += "（核心パラメータ変更）";
   if(StringLen(s) == 0)
      return "fusion（既定）";
   return "F" + s;
  }

string TrimStr(const string text)
  {
   string s = text;
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
  }

//--- "EURUSD, GBPUSD.a" → 配列（空なら 0）
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
      string p = TrimStr(parts[i]);
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
   return cnt;
  }

//--- 銘柄名 → s_nom の表の名前（SPEC §10.3）
//    1) InpSymbolMap（例 "m.EURUSD=EURUSD;GOLD#=XAUUSD"）
//    2) 先頭6文字（GOLD〜 は XAUUSD。FE_SymbolBase）が表にあればそれ
//    3) 英数字だけにして表の名前（と GOLD）をただ1つ含むならそれ（m.EURUSD・#XAUUSD など）
//    4) それ以外は 2) の名前（表にない銘柄。s_nom は InpSpreadPointsDefault）
//    2)〜4) は照合ハーネス fusion/mt5_parity.py の symbol_base と同じ
string ResolveBase(const string sym)
  {
   string mp = InpSymbolMap;
   StringReplace(mp, ",", ";");
   string parts[];
   int np = StringSplit(mp, StringGetCharacter(";", 0), parts);
   for(int i = 0; i < np; i++)
     {
      string kv[];
      if(StringSplit(parts[i], StringGetCharacter("=", 0), kv) != 2)
         continue;
      string k = TrimStr(kv[0]);
      string v = TrimStr(kv[1]);
      StringToUpper(v);
      if(k == sym && StringLen(v) > 0)
         return v;
     }
   string b = FE_SymbolBase(sym);
   if(FE_NominalSpread(b) > 0.0)
      return b;
   string u = "";
   int len = StringLen(sym);
   for(int j = 0; j < len; j++)
     {
      ushort ch = StringGetCharacter(sym, j);
      if(ch >= 'a' && ch <= 'z')
         ch = (ushort)(ch - 32);
      if((ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9'))
         u += ShortToString(ch);
     }
   string names[];
   double vals[];
   int nn = FE_SpreadTable(names, vals);               // 表の名前は FE_SpreadTable の1か所だけ
   string hit = "";
   int nh = 0;
   for(int q = 0; q < nn; q++)
      if(StringFind(u, names[q]) >= 0)
        {
         hit = names[q];
         nh++;
        }
   if(StringFind(u, "GOLD") >= 0 && hit != "XAUUSD")
     {
      hit = "XAUUSD";
      nh++;
     }
   return (nh == 1) ? hit : b;
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
//| 監視の権利（同じ口座・マジック・銘柄を2つのチャートで動かさない）   |
//|  端末のグローバル変数（一時。端末を閉じると消える）に持ち主を書く。 |
//|  持ち主は 10 秒ごとに生存記録を書き、60 秒途切れたら引き取れる。    |
//+------------------------------------------------------------------+
//--- 口座番号（起動直後はまだ 0 のことがあるので、使うたびに読む）
long AccountLogin(void)
  {
   return AccountInfoInteger(ACCOUNT_LOGIN);
  }

//--- 口座・マジック・銘柄ごとのグローバル変数の名前の頭（名前は 63 文字まで）
string GvBase(CSymbolCtx *c)
  {
   string b = "FUS" + IntegerToString(AccountLogin()) + "_" + IntegerToString(InpMagicNumber) + "_" + c.tag;
   if(StringLen(b) > 40)
      b = StringSubstr(b, 0, 40);
   return b;
  }

//--- 監視の権利の名前（グローバル変数は端末ごとなので、マジックと銘柄で足りる）
string LockNameOf(const long magic, const string sym)
  {
   string b = "FUSL_" + IntegerToString(magic) + "_" + FileTag(sym);
   if(StringLen(b) > 60)
      b = StringSubstr(b, 0, 60);
   return b;
  }

string LockName(CSymbolCtx *c)
  {
   return LockNameOf(InpMagicNumber, c.sym);
  }

//--- 監視の権利を取る。持ち主がいれば、止まっていると確かめられたときだけ引き取る:
//    起動時（fromInit）は、生存記録があってそれが FUS_STALE_LOCK_SEC より古いとき（異常終了の後に別のチャートに付け直した）。
//    巡回中は、生存記録の値が自分の時計で FUS_STALE_LOCK_SEC 以上・2回続けて変わらないとき（PC のスリープ明けに
//    持ち主より先に確かめた・同時に起動して持ち主がまだ生存記録を書いていない、では引き取らない）
bool AcquireLock(CSymbolCtx *c, const bool fromInit)
  {
   if(g_tester)
     {
      c.locked = true;
      return true;
     }
   string nm = c.lockName;
   string hb = nm + "H";
   if(!GlobalVariableCheck(nm))
      GlobalVariableTemp(nm);
   bool own = GlobalVariableSetOnCondition(nm, g_token, 0.0);
   if(!own)
     {
      double cur = GlobalVariableGet(nm);
      if(cur == g_token)
         own = true;
      else
        {
         bool hasHb = GlobalVariableCheck(hb);
         double last = hasHb ? GlobalVariableGet(hb) : 0.0;
         bool stale = false;
         if(fromInit)
            stale = (hasHb && (double)TimeLocal() - last > FUS_STALE_LOCK_SEC);
         else
           {
            uint now = NowMs();
            if(c.lockSeenMs == 0 || last != c.lockSeenHb || now - c.lockCheckMs > 3 * FUS_RELOCK_MS)
              {
               c.lockSeenHb = last;                     // 新しい値（または久しぶりの確認）：ここから数え直す
               c.lockSeenMs = now;
               c.lockSame = 0;
              }
            else
               c.lockSame++;
            c.lockCheckMs = now;
            stale = (c.lockSame >= 2 && now - c.lockSeenMs >= (uint)FUS_STALE_LOCK_SEC * 1000);
           }
         if(stale)                                      // 持ち主が止まっている（異常終了など）
           {
            own = GlobalVariableSetOnCondition(nm, g_token, cur);
            if(own)
               PrintFormat("[FUSION] %s の監視の権利の持ち主が止まっているため引き取ります", c.sym);
           }
        }
     }
   c.locked = own;
   if(own)
     {
      c.lockSeenMs = 0;
      c.lockSame = 0;
      if(!GlobalVariableCheck(hb))
         GlobalVariableTemp(hb);
      GlobalVariableSet(hb, (double)TimeLocal());
     }
   else
      c.note = "別のチャートが監視中";
   return own;
  }

void ReleaseLock(CSymbolCtx *c)
  {
   if(g_tester || !c.locked)
      return;
   if(GlobalVariableCheck(c.lockName) && GlobalVariableGet(c.lockName) == g_token)
     {
      GlobalVariableDel(c.lockName);
      GlobalVariableDel(c.lockName + "H");
     }
   c.locked = false;
  }

//--- 権利がなかった銘柄は、1分ごとに取り直しを試みる（別のチャートの EA が外されたら引き継ぐ）
bool TryRelock(CSymbolCtx *c)
  {
   uint now = NowMs();
   if(c.relockMs != 0 && now - c.relockMs < FUS_RELOCK_MS)
      return false;
   c.relockMs = now;
   if(!AcquireLock(c, false))
      return false;
   c.note = "";
   PrintFormat("[FUSION] %s の監視を引き継ぎます（別のチャートの EA が止まった）", c.sym);
   return true;
  }

//--- 監視の権利を失った（別のチャートの EA が引き取った）：この銘柄の処理をすべて止める。
//    注文・建玉は引き取った側が口座から引き継ぐので、ここでは何も送らない
void LoseLock(CSymbolCtx *c)
  {
   CloseLogs(c);
   c.locked = false;
   c.ready = false;
   c.initStartMs = 0;
   c.lastForming = 0;
   c.relockMs = NowMs();
   c.lockSeenMs = 0;
   c.lockSame = 0;
   c.real.Reset();
   c.nfHas = false;
   c.note = "別のチャートが監視中";
   c.alert = "";
   g_panelDirty = true;
   Notify(StringFormat("%s %s 注意: 監視の権利を別のチャートの FX_Fusion_EA が持っています。ここでの監視・注文・決済をやめました。同じ EA を複数のチャートに付けていないか確かめてください",
                       ModeTag(), c.sym), 1);
  }

//--- 10秒ごとに、権利をまだ持っているかを確かめてから生存記録を書く
void Heartbeats(void)
  {
   if(g_tester)
      return;
   uint now = NowMs();
   if(g_hbMs != 0 && now - g_hbMs < FUS_HEARTBEAT_MS)
      return;
   g_hbMs = now;
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(!c.locked)
         continue;
      double cur = GlobalVariableCheck(c.lockName) ? GlobalVariableGet(c.lockName) : 0.0;
      if(cur != g_token)
        {
         bool again = false;
         if(cur == 0.0)
           {
            //--- 権利の変数が消えていた（グローバル変数の一覧から消された等）：まだ誰も取っていなければ取り直す
            if(!GlobalVariableCheck(c.lockName))
               GlobalVariableTemp(c.lockName);
            again = GlobalVariableSetOnCondition(c.lockName, g_token, 0.0);
           }
         if(!again)
           {
            LoseLock(c);
            continue;
           }
        }
      if(!GlobalVariableCheck(c.lockName + "H"))
         GlobalVariableTemp(c.lockName + "H");
      GlobalVariableSet(c.lockName + "H", (double)TimeLocal());
     }
  }

//+------------------------------------------------------------------+
//| ログ（CSV）                                                       |
//+------------------------------------------------------------------+
int LogCommonFlag(void)
  {
   return InpLogsCommon ? FILE_COMMON : 0;
  }

void OpenLogs(CSymbolCtx *c)
  {
   CloseLogs(c);
   c.tradesLogged = 0;
   c.barsLogged = 0;
   if(!g_logs)
      return;
   int common = LogCommonFlag();
   FolderCreate("FusionEA", common);
   ArchiveLogs(c, common);                       // 前の回のログ（LIVE 行を含む）を FusionEA/old/ に残す
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
   //--- 判定に使った足（照合で Python に同じ足を渡すため。fusion/data.load_mt5_csv で読める）
   c.hBars = FileOpen(base + "_bars.csv", flags);
   if(c.hBars != INVALID_HANDLE)
     {
      FileWriteString(c.hBars, "Time,Open,High,Low,Close\r\n");
      WriteNewBars(c);
     }
   //--- 照合に必要な設定（最初に読み込んだ足・s_nom・時差・構成）。ASCII だけで書く
   int hi = FileOpen(base + "_info.csv", flags);
   if(hi != INVALID_HANDLE)
     {
      SFusionParams p;
      p = c.eng.m_p;
      FileWriteString(hi, "key,value\r\n");
      FileWriteString(hi, "ea,FX_Fusion_EA 1.01 (FUSION-CORE v1.0)\r\n");
      FileWriteString(hi, "symbol," + c.sym + "\r\nbase," + c.base + "\r\n");
      FileWriteString(hi, "s_nom," + DoubleToString(p.s_nom, 8) + "\r\nis_xau," + (p.is_xau ? "1" : "0") + "\r\n");
      FileWriteString(hi, "server_offset_h," + IntegerToString(p.server_offset_h) + "\r\n");
      FileWriteString(hi, "first_bar_time," + ((c.eng.m_n > 0) ? FE_Time(c.eng.m_T[0]) : "") + "\r\n");
      FileWriteString(hi, "first_eval_time," + ((c.eng.m_first >= 0) ? FE_Time(c.eng.m_T[c.eng.m_first]) : "") + "\r\n");
      FileWriteString(hi, "bars_loaded," + IntegerToString(c.eng.m_n) + "\r\nhistory_bars_input," + IntegerToString(InpHistoryBars) + "\r\n");
      FileWriteString(hi, "config," + ConfigTag() + "\r\ncore_changed," + (CoreChanged() ? "1" : "0") + "\r\n");
      FileWriteString(hi, StringFormat("switches,g3=%d d1_gate=%d gap_gate=%d clear_gate=%d cf_scope=%d support_gate=%d sl_mode=%d p3=%d\r\n",
                                       p.g3 ? 1 : 0, p.d1_gate, p.gap_gate ? 1 : 0, p.clear_gate ? 1 : 0, p.cf_scope,
                                       p.support_gate ? 1 : 0, p.sl_mode, p.p3 ? 1 : 0));
      FileWriteString(hi, StringFormat("params,N_BIG=%d N_SMALL=%d ZONE_ATR=%.4f SLOPE_MIN=%.4f ENTRY_BUF_ATR=%.4f SL_BUF_ATR=%.4f R_MIN_ATR=%.4f R_MAX_ATR=%.4f N_D1=%d TOL_LV=%.4f TOL_S=%.4f CF_MIN_TOUCH=%d RR_CF=%.4f GAP_HI=%.4f LVL_MAX_ATR=%.4f\r\n",
                                       p.n_big, p.n_small, p.zone_atr, p.slope_min, p.entry_buf_atr, p.sl_buf_atr, p.r_min_atr, p.r_max_atr,
                                       p.n_d1, p.tol_lv, p.tol_s, p.cf_min_touch, p.rr_cf, p.gap_hi, p.lvl_max_atr));
      FileWriteString(hi, "extra_closed," + InpExtraClosedDays + "\r\nextra_early," + InpExtraEarlyDays + "\r\n");
      FileWriteString(hi, "login," + IntegerToString(AccountLogin()) + "\r\nmagic," + IntegerToString(InpMagicNumber) + "\r\n");
      FileWriteString(hi, "auto_trade," + (InpAutoTrade ? "1" : "0") + "\r\ntester," + (g_tester ? "1" : "0") + "\r\n");
      FileClose(hi);
     }
  }

//--- 前の回のログを FusionEA/old/<銘柄>_<日時>/ に移し、古いものは InpLogKeep 世代まで残す
void ArchiveLogs(CSymbolCtx *c, const int common)
  {
   if(InpLogKeep <= 0)
      return;
   string src = "FusionEA\\" + c.tag;
   if(!FileIsExist(src + "_eval.csv", common) && !FileIsExist(src + "_trades.csv", common))
      return;
   MqlDateTime dt;
   TimeToStruct(TimeLocal(), dt);
   string stamp = StringFormat("%04d%02d%02d_%02d%02d%02d", dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);
   string dir = "FusionEA\\old\\" + c.tag + "_" + stamp;
   FolderCreate("FusionEA\\old", common);
   FolderCreate(dir, common);
   string suf[4] = {"_eval.csv", "_trades.csv", "_bars.csv", "_info.csv"};
   for(int i = 0; i < 4; i++)
     {
      string f = src + suf[i];
      if(!FileIsExist(f, common))
         continue;
      if(!FileMove(f, common, dir + "\\" + c.tag + suf[i], common | FILE_REWRITE))
         PrintFormat("[FUSION] %s を FusionEA\\old に移せません（%d）。上書きします", f, GetLastError());
     }
   PruneArchives(c, common);
  }

void PruneArchives(CSymbolCtx *c, const int common)
  {
   string prefix = c.tag + "_";
   int want = StringLen(prefix) + 15;                  // <銘柄>_YYYYMMDD_HHMMSS
   string names[];
   int cnt = 0;
   string found = "";
   long h = FileFindFirst("FusionEA\\old\\" + prefix + "*", found, common);
   if(h == INVALID_HANDLE)
      return;
   do
     {
      string nm = found;
      int len = StringLen(nm);
      if(len > 0 && StringGetCharacter(nm, len - 1) == '\\')
         nm = StringSubstr(nm, 0, len - 1);
      if(StringLen(nm) == want && StringFind(nm, prefix) == 0)
        {
         ArrayResize(names, cnt + 1);
         names[cnt] = nm;
         cnt++;
        }
     }
   while(FileFindNext(h, found));
   FileFindClose(h);
   if(cnt <= InpLogKeep)
      return;
   for(int i = 1; i < cnt; i++)                          // 古い順（名前の日時の順）に並べる
     {
      string key = names[i];
      int j = i - 1;
      while(j >= 0 && StringCompare(names[j], key) > 0)
        {
         names[j + 1] = names[j];
         j--;
        }
      names[j + 1] = key;
     }
   for(int k = 0; k < cnt - InpLogKeep; k++)
     {
      string d = "FusionEA\\old\\" + names[k];
      FolderClean(d, common);
      FolderDelete(d, common);
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
   if(c.hBars != INVALID_HANDLE)
      FileClose(c.hBars);
   c.hEval = INVALID_HANDLE;
   c.hTrades = INVALID_HANDLE;
   c.hBars = INVALID_HANDLE;
  }

//--- 実取引のログの名前。テスターでは別の名前（<銘柄>_real_tester.csv。テストごとに作り直す）にして、
//    ライブの <銘柄>_real.csv（追記だけ）に模擬の取引が混ざらないようにする
string RealLogName(CSymbolCtx *c)
  {
   return "FusionEA\\" + c.tag + (g_tester ? "_real_tester.csv" : "_real.csv");
  }

//--- 実取引の1行を <銘柄>_real.csv に追記する（起動・読み直しでも消さない。最適化中は書かない）
void WriteRealTrade(CSymbolCtx *c, const datetime entryT, const int dir, const double entry, const double initSl,
                    const datetime exitT, const string why, const double r, const datetime keyT, const int score,
                    const ulong ticket, const double exitPx, const double volume, const double planned,
                    const double profit, const double swap, const double comm)
  {
   if(g_optim)
      return;
   int common = LogCommonFlag();
   FolderCreate("FusionEA", common);
   string name = RealLogName(c);
   int h = FileOpen(name, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | common);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("[FUSION] %s を開けません（%d）。実取引の記録を書けませんでした", name, GetLastError());
      return;
     }
   if(FileSize(h) == 0)
      FileWriteString(h, FUS_REAL_HEADER + "\r\n");
   FileSeek(h, 0, SEEK_END);
   double slip = (planned > 0.0 && c.point > 0.0) ? (entry - planned) * dir / c.point : 0.0;
   string line = FE_Time(entryT) + "," + IntegerToString(dir) + "," + DoubleToString(entry, 8) + "," + DoubleToString(initSl, 8) + "," +
                 FE_Time(exitT) + "," + why + "," + DoubleToString(r, 6) + "," + ((keyT > 0) ? FE_Time(keyT) : "") + "," +
                 IntegerToString(score) + "," + IntegerToString((long)ticket) + "," + DoubleToString(exitPx, 8) + "," +
                 DoubleToString(volume, 2) + "," + ((planned > 0.0) ? DoubleToString(planned, 8) : "") + "," +
                 ((planned > 0.0) ? DoubleToString(slip, 1) : "") + "," + DoubleToString(profit, 2) + "," +
                 DoubleToString(swap, 2) + "," + DoubleToString(comm, 2) + "," + IntegerToString(AccountLogin()) + "," +
                 IntegerToString(InpMagicNumber);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
  }

//--- 送った通知を FusionEA/notify_log.csv に追記する（UTF-8。起動しても消さない）
void LogNotify(const string msg)
  {
   if(!g_logs || g_tester)
      return;
   int common = LogCommonFlag();
   FolderCreate("FusionEA", common);
   int h = FileOpen("FusionEA\\notify_log.csv", FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE | common, ',', CP_UTF8);
   if(h == INVALID_HANDLE)
      return;
   if(FileSize(h) == 0)
      FileWriteString(h, "server_time,local_time,login,magic,message\r\n");
   FileSeek(h, 0, SEEK_END);
   string m = msg;
   StringReplace(m, "\"", "\"\"");
   FileWriteString(h, TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS) + "," + TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS) + "," +
                   IntegerToString(AccountLogin()) + "," + IntegerToString(InpMagicNumber) + ",\"" + m + "\"\r\n");
   FileClose(h);
  }

//--- 稼働中（LIVE）の評価行・仮想取引を、追記だけのファイルにも書く（<銘柄>_live.csv・<銘柄>_live_trades.csv）。
//    _eval・_trades は起動・読み直しのたびに作り直して old/ に世代で残すだけなので、稼働中の判定の記録をここで失わずに残す。
//    テスター・最適化では書かない（テストごとに _eval・_trades を見ればよい）
void AppendLive(CSymbolCtx *c, const string suffix, const string header, const string lines)
  {
   if(!g_logs || g_tester || StringLen(lines) == 0)
      return;
   int common = LogCommonFlag();
   FolderCreate("FusionEA", common);
   string name = "FusionEA\\" + c.tag + suffix;
   int h = FileOpen(name, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | common);
   if(h == INVALID_HANDLE)
     {
      if(LogDue(c.logMs))
         PrintFormat("[FUSION] %s を開けません（%d）。稼働中の記録を書けませんでした", name, GetLastError());
      return;
     }
   if(FileSize(h) == 0)
      FileWriteString(h, header + "\r\n");
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, lines);
   FileClose(h);
  }

//--- エンジンの出力（評価行・取引・イベント）を書き出し、通知する。
//    cutoff>0 なら、その時刻より前の足のイベントは通知しない（追いつき処理）。戻り値は省いた通知の数
int DrainOutputs(CSymbolCtx *c, const bool live, const datetime cutoff)
  {
   string liveRows = "";
   string liveTrades = "";
   for(int i = 0; i < c.eng.m_nrows; i++)
     {
      string row = FE_EvalCsv(c.eng.m_rows[i]) + "\r\n";
      if(c.hEval != INVALID_HANDLE)
         FileWriteString(c.hEval, row);
      if(c.eng.m_rows[i].phase == 1)
         liveRows += row;
     }
   c.eng.m_nrows = 0;
   while(c.tradesLogged < c.eng.m_ntrades)
     {
      string tr = FE_TradeCsv(c.eng.m_trades[c.tradesLogged]) + "\r\n";
      if(c.hTrades != INVALID_HANDLE)
         FileWriteString(c.hTrades, tr);
      if(c.eng.m_trades[c.tradesLogged].phase == 1 && c.eng.m_trades[c.tradesLogged].reason != XR_END)
         liveTrades += tr;
      c.tradesLogged++;
     }
   AppendLive(c, "_live.csv", FE_EvalHeader(), liveRows);
   AppendLive(c, "_live_trades.csv", FE_TradeHeader(), liveTrades);
   int skipped = 0;
   for(int j = 0; j < c.eng.m_nev; j++)
     {
      bool notify = live && (cutoff == 0 || c.eng.m_ev[j].bar_time >= cutoff);
      if(live && !notify && !InpAutoTrade && c.eng.m_ev[j].etype != EV_ZONE && c.eng.m_ev[j].etype != EV_UPDATE)
         skipped++;
      HandleEvent(c, c.eng.m_ev[j], notify);
     }
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
   return skipped;
  }

//+------------------------------------------------------------------+
//| 通知（SPEC §16.2。255文字以内、送信は間隔をあけて順に）             |
//+------------------------------------------------------------------+
void Notify(const string msg)
  {
   Notify(msg, 0);
  }

//--- prio=1 は重要（約定・決済・休場明け・要対応）。通常の通知より先に送り、古くなっても捨てない
void Notify(const string msg, const int prio)
  {
   string m = msg;
   if(StringLen(m) > 255)
      m = StringSubstr(m, 0, 255);
   Print(m);
   if(g_tester)
      return;
   LogNotify(m);
   if(InpAlertPopup)
      Alert(m);
   if(!InpPushNotify)
      return;
   int pos = g_nq;
   if(prio > 0)
     {
      pos = 0;
      while(pos < g_nq && g_qPrio[pos] > 0)
         pos++;
     }
   ArrayResize(g_queue, g_nq + 1, 64);
   ArrayResize(g_qPrio, g_nq + 1, 64);
   ArrayResize(g_qMs, g_nq + 1, 64);
   for(int i = g_nq; i > pos; i--)
     {
      g_queue[i] = g_queue[i - 1];
      g_qPrio[i] = g_qPrio[i - 1];
      g_qMs[i] = g_qMs[i - 1];
     }
   g_queue[pos] = m;
   g_qPrio[pos] = prio;
   g_qMs[pos] = GetTickCount();
   g_nq++;
  }

void QueueRemove(const int idx)
  {
   for(int i = idx + 1; i < g_nq; i++)
     {
      g_queue[i - 1] = g_queue[i];
      g_qPrio[i - 1] = g_qPrio[i];
      g_qMs[i - 1] = g_qMs[i];
     }
   g_nq--;
   ArrayResize(g_queue, g_nq, 64);
   ArrayResize(g_qPrio, g_nq, 64);
   ArrayResize(g_qMs, g_nq, 64);
  }

//--- SendNotification は1秒に2件・1分に10件までなので、6.5秒あけて1件ずつ送る
void FlushNotifications(void)
  {
   if(g_nq <= 0)
      return;
   uint now = GetTickCount();
   for(int i = g_nq - 1; i >= 0; i--)
      if(g_qPrio[i] == 0 && now - g_qMs[i] > FUS_NOTIFY_OLD_MS)
        {
         PrintFormat("[FUSION] 古くなった通知は送らない: %s", g_queue[i]);
         QueueRemove(i);
        }
   if(g_nq <= 0)
      return;
   if(g_lastSendMs != 0 && now - g_lastSendMs < FUS_NOTIFY_GAP_MS)
      return;
   if(TerminalInfoInteger(TERMINAL_NOTIFICATIONS_ENABLED) == 0)
     {
      if(!g_pushWarned)
         Print("[FUSION] 端末のプッシュ通知が無効です（ツール→オプション→通知）。通知はエキスパートログと notify_log.csv にだけ残します");
      g_pushWarned = true;
      g_nq = 0;
      ArrayResize(g_queue, 0);
      ArrayResize(g_qPrio, 0);
      ArrayResize(g_qMs, 0);
      return;
     }
   g_lastSendMs = now;
   ResetLastError();
   if(SendNotification(g_queue[0]))
     {
      QueueRemove(0);
      return;
     }
   int err = GetLastError();
   if(err == 4518)                                // ERR_NOTIFICATION_TOO_FREQUENT：残して次の機会に送る
      return;
   PrintFormat("[FUSION] プッシュ通知の送信に失敗（%d）。MT5 の設定（オプション→通知）を確認してください: %s", err, g_queue[0]);
   QueueRemove(0);
  }

string Px(CSymbolCtx *c, const double v)
  {
   return DoubleToString(v, c.digits);
  }

string DirName(const int d)
  {
   return (d == 1) ? "買い" : "売り";
  }

//--- 仮想建玉の短い説明（読み直しの通知用）
string VPosText(CSymbolCtx *c, const bool active, const int dir, const double entry, const double sl)
  {
   if(!active)
      return "なし";
   return DirName(dir) + " " + Px(c, entry) + " SL" + Px(c, sl);
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
         bool newKey = (!c.nfHas || c.nfDir != e.dir || c.nfKeyTime != e.s.key_time);
         bool send = newKey;
         if(!send && (MathAbs(e.price - c.nfPrice) > 0.2 * e.s.atr || MathAbs(e.sl - c.nfSl) > 0.2 * e.s.atr))
            send = true;                                // 同じ key は 0.2ATR を超えて動いたときだけ
         if(send)
           {
            c.nfHas = true;
            c.nfDir = e.dir;
            c.nfKeyTime = e.s.key_time;
            c.nfPrice = e.price;
            c.nfSl = e.sl;
            if(notify)
               Notify(MsgArmed(c, e.s, newKey ? "" : "修正 "));
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
                                FE_Time(e.s.key_time)), 1);
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
                                FE_ReasonName(e.code), Px(c, e.price), e.value, held), 1);
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
            Notify(StringFormat("%s %s GAP_FALLBACK 休場明け（12時間以上の空き）: %s", ModeTag(), c.sym, what), 1);
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
//|  ・確定足ごとに「置きたい注文」を決め（RealOnBar）、実際の注文を   |
//|    それに合わせる（RealApply。置けない・直せない・取消せないときは |
//|    同じ足の中で再試行。間隔は 10 秒、証拠金不足・取引停止などの    |
//|    拒否は 1 分・5 分と広げ、市場が閉まっていたら次のティックまで）。|
//|  ・週末・休場・休場明けの決済は、建玉が消えるまで再試行する。決済 |
//|    足の終わりの 2 分前からは、市場が閉じる前に決済する。切断・停止 |
//|    の間に決済足・休場明けを過ぎた建玉は、つながったらすぐ決済する。|
//|  ・注文が消えたら、履歴で約定か取消かを確かめる。約定なら約定済み |
//|    集合に入れ、その足では新しく置かない（約定してすぐ SL で閉じた |
//|    場合も記録し、同じセットアップに入り直さない。R06）。           |
//|  ・同じ建玉は _real.csv に1回だけ記録する（記録した建玉 ID を覚える）。|
//|  ・口座の引き継ぎ・発注は、取引サーバーにつながって 10 秒たってから|
//|    行う。つながり直したら口座の状態を読み直す。                    |
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

//--- 初期 SL を置くグローバル変数（建玉 ID ごと）
string GvIsl(CSymbolCtx *c, const long posId)
  {
   return GvBase(c) + "_I" + IntegerToString(posId);
  }

//--- 自分の建玉（1銘柄1建玉。複数あれば最初に見つかったもの）
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

bool HasOwnPosition(const string sym)
  {
   ulong tk = 0;
   return FindPosition(sym, tk);
  }

//--- 自分の建玉の数（1銘柄1建玉のはず）
int CountOwnPositions(const string sym)
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         n++;
     }
   return n;
  }

//--- 建玉 ID の建玉がいま開いているか
bool PositionIdOpen(const long pid)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk != 0 && PositionGetInteger(POSITION_IDENTIFIER) == pid)
         return true;
     }
   return false;
  }

//--- 建玉 ID の決済の約定が履歴にあるか（閉じたことを確かめる）
bool PositionClosedInHistory(const long pid)
  {
   if(!HistorySelectByPosition(pid))
      return false;
   int nd = HistoryDealsTotal();
   for(int i = 0; i < nd; i++)
     {
      ulong dt = HistoryDealGetTicket(i);
      if(dt == 0)
         continue;
      long et = HistoryDealGetInteger(dt, DEAL_ENTRY);
      if(et == DEAL_ENTRY_OUT || et == DEAL_ENTRY_OUT_BY || et == DEAL_ENTRY_INOUT)
         return true;
     }
   return false;
  }

//--- 自分の待機注文の数（except は数えない）
int CountOwnOrders(const string sym, const ulong except)
  {
   int n = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0 || t == except)
         continue;
      if(OrderGetString(ORDER_SYMBOL) == sym && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber)
         n++;
     }
   return n;
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

//--- 現在値から逆指値・SL を置ける最小の距離。STOPS_LEVEL が 0 のブローカーには「変動（スプレッド程度）」の意味の
//    ものがあるので、そのときは現在のスプレッドを下限にする
double MinStopDist(CSymbolCtx *c, const double ask, const double bid)
  {
   double d = (double)SymbolInfoInteger(c.sym, SYMBOL_TRADE_STOPS_LEVEL) * c.point;
   if(d <= 0.0)
      d = ask - bid;
   return d;
  }

double FreezeDist(CSymbolCtx *c)
  {
   return (double)SymbolInfoInteger(c.sym, SYMBOL_TRADE_FREEZE_LEVEL) * c.point;
  }

//--- 端末・EA・口座の理由で取引できないか（全銘柄に共通。空なら取引できる）
string GlobalTradeBlock(void)
  {
   if(g_tester)
      return "";
   if(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) == 0)
      return "端末のアルゴ取引が OFF";
   if(MQLInfoInteger(MQL_TRADE_ALLOWED) == 0)
      return "EA のアルゴ取引が許可されていない（EA の設定の「アルゴ取引を許可」）";
   if(AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) == 0)
      return "口座で取引できない（投資家パスワード・口座の制限）";
   if(AccountInfoInteger(ACCOUNT_TRADE_EXPERT) == 0)
      return "口座で EA の取引が許可されていない";
   return "";
  }

//--- 銘柄の取引モードで取引できないか（dir=0 は決済・取消だけ。dir=±1 はその向きの新規。空なら取引できる）
string SymbolTradeBlock(CSymbolCtx *c, const int dir)
  {
   if(g_tester)
      return "";
   long mode = SymbolInfoInteger(c.sym, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED)
      return "銘柄が取引停止";
   if(dir != 0 && mode == SYMBOL_TRADE_MODE_CLOSEONLY)
      return "銘柄が決済のみ";
   if(dir == 1 && mode == SYMBOL_TRADE_MODE_SHORTONLY)
      return "銘柄が売りのみ";
   if(dir == -1 && mode == SYMBOL_TRADE_MODE_LONGONLY)
      return "銘柄が買いのみ";
   return "";
  }

//--- 取引できるか（dir=0 は決済・取消だけ。dir=±1 はその向きの新規）
bool CanTrade(CSymbolCtx *c, const int dir, string &why)
  {
   why = GlobalTradeBlock();
   if(StringLen(why) == 0)
      why = SymbolTradeBlock(c, dir);
   return (StringLen(why) == 0);
  }

//--- 端末・EA・口座の取引の可否が変わったら、パネルに出して1回だけ知らせる（全銘柄で1通）
void CheckGlobalPermission(void)
  {
   string why = GlobalTradeBlock();
   if(why == g_tradeNote)
      return;
   if(StringLen(why) > 0)
      Notify(StringFormat("%s 注意: 自動売買ができません（%s）。全銘柄の注文・決済が止まっています", ModeTag(), why), 1);
   else
      Print("[FUSION] 自動売買ができる状態に戻りました");
   g_tradeNote = why;
   g_panelDirty = true;
  }

//--- 銘柄の取引モードの可否が変わったら、パネルに出して1回だけ知らせる（銘柄ごと）
void CheckTradePermission(CSymbolCtx *c)
  {
   string why = SymbolTradeBlock(c, 0);
   if(why == c.real.tradeNote)
      return;
   if(StringLen(why) > 0)
      Notify(StringFormat("%s %s 注意: 自動売買ができません（%s）。この銘柄の注文・決済は止まっています", ModeTag(), c.sym, why), 1);
   else
      PrintFormat("[FUSION] %s 自動売買ができる状態に戻りました", c.sym);
   c.real.tradeNote = why;
   g_panelDirty = true;
  }

//--- 再試行の間隔（拒否の種類で決める）。価格の変化・接続・一時的な混雑は FUS_RETRY_MS のまま、
//    証拠金不足・取引停止・要求が多すぎる・注文の上限などは 1分、5分…と広げる（サーバーに同じ要求を送り続けない）。
//    rc=0 は要求を送らずに待った（STOPS_LEVEL の内側など）
uint FailDelayMs(const uint rc, const int fails)
  {
   if(rc == 0 || rc == TRADE_RETCODE_REQUOTE || rc == TRADE_RETCODE_PRICE_CHANGED || rc == TRADE_RETCODE_PRICE_OFF ||
      rc == TRADE_RETCODE_TIMEOUT || rc == TRADE_RETCODE_CONNECTION || rc == TRADE_RETCODE_INVALID_PRICE ||
      rc == TRADE_RETCODE_LOCKED || rc == TRADE_RETCODE_FROZEN || rc == TRADE_RETCODE_ERROR)
      return FUS_RETRY_MS;
   return (fails <= 1) ? FUS_BACKOFF1_MS : FUS_BACKOFF2_MS;
  }

//--- 市場が閉まっていた（MARKET_CLOSED）：この銘柄の注文・決済を、新しいティックが来るまで（最長 FUS_MKT_HOLD_MS）止める
void HoldMarket(CSymbolCtx *c)
  {
   MqlTick tk;
   c.real.holdMsc = 0;
   if(SymbolInfoTick(c.sym, tk))
      c.real.holdMsc = tk.time_msc;
   c.real.holdMs = NowMs();
   if(c.real.holdMs == 0)
      c.real.holdMs = 1;
   if(LogDue(c.real.logMs))
      PrintFormat("[FUSION] %s 市場が閉まっている（MARKET_CLOSED）。新しいティックが来るまで注文・決済を待ちます", c.sym);
  }

//--- 市場が閉まっていたため待っているか（新しいティックが来たか、FUS_MKT_HOLD_MS たったら待つのをやめる）
bool MarketHeld(CSymbolCtx *c)
  {
   if(c.real.holdMs == 0)
      return false;
   MqlTick tk;
   bool fresh = (SymbolInfoTick(c.sym, tk) && tk.time_msc > c.real.holdMsc);
   if(fresh || NowMs() - c.real.holdMs >= FUS_MKT_HOLD_MS)
     {
      c.real.holdMs = 0;
      c.real.holdMsc = 0;
      return false;
     }
   return true;
  }

//--- ロット＝floor(残高×risk%÷(R÷tick_size×tick_value)÷lot_step)×lot_step を [min, max] に丸める。
//    ratio は「実際のロット÷目標のロット」（最小ロットに切り上げたときに 1 を超える）
double CalcLotSize(const string sym, const double slDist, double &ratio)
  {
   ratio = 1.0;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;
   double tickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double minLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(tickSize <= 0 || tickValue <= 0 || slDist <= 0 || step <= 0 || riskMoney <= 0)
      return 0.0;
   double perLot = (slDist / tickSize) * tickValue;
   if(perLot <= 0)
      return 0.0;
   double raw = riskMoney / perLot;
   double lots = MathFloor(raw / step) * step;
   if(lots < minLot)
     {
      ratio = (raw > 0.0) ? minLot / raw : 99.0;
      lots = minLot;
     }
   if(lots > maxLot)
      lots = maxLot;
   int vd = 0;
   double s = step;
   while(s < 1.0 - 1e-9 && vd < 8)
     {
      s *= 10.0;
      vd++;
     }
   return NormalizeDouble(lots, vd);
  }

//--- 注文の結果を確かめる。戻り値 FUS_CXL_FAIL（まだ有効）/ FILLED（約定・一部約定）/ DONE（約定せずに消えた）/ UNKNOWN（履歴待ち）
int OrderOutcome(const ulong ticket)
  {
   if(OrderSelect(ticket))
      return FUS_CXL_FAIL;
   if(!HistoryOrderSelect(ticket))
      return FUS_CXL_UNKNOWN;
   long st = HistoryOrderGetInteger(ticket, ORDER_STATE);
   double vi = HistoryOrderGetDouble(ticket, ORDER_VOLUME_INITIAL);
   double vc = HistoryOrderGetDouble(ticket, ORDER_VOLUME_CURRENT);
   if(st == ORDER_STATE_FILLED || st == ORDER_STATE_PARTIAL || vi - vc > 1e-10)
      return FUS_CXL_FILLED;
   return FUS_CXL_DONE;
  }

//--- 待機注文を1つ取消す。戻り値 FUS_CXL_*（取消の前後に約定・一部約定していたら FILLED。結果がまだ履歴になければ UNKNOWN）
int CancelTicket(CSymbolCtx *c, const ulong ticket, const string why)
  {
   if(OrderSelect(ticket))
     {
      //--- すでに一部約定している注文は、残りを取消しても「約定していた」として扱う（建玉がある。新しい注文は出さない）
      bool partial = (OrderGetDouble(ORDER_VOLUME_INITIAL) - OrderGetDouble(ORDER_VOLUME_CURRENT) > 1e-10);
      double freeze = FreezeDist(c);
      MqlTick tk;
      if(freeze > 0.0 && SymbolInfoTick(c.sym, tk))
        {
         long type = OrderGetInteger(ORDER_TYPE);
         double op = OrderGetDouble(ORDER_PRICE_OPEN);
         bool buySide = (type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_BUY_LIMIT || type == ORDER_TYPE_BUY_STOP_LIMIT);
         double dist = buySide ? MathAbs(op - tk.ask) : MathAbs(tk.bid - op);
         if(dist < freeze)
           {
            if(LogDue(c.real.logMs))
               PrintFormat("[FUSION] %s 注文 #%I64u は FREEZE_LEVEL の内側のため、取消を待ちます（%s）", c.sym, ticket, why);
            c.real.lastRc = 0;
            return FUS_CXL_FAIL;
           }
        }
      if(g_trade.OrderDelete(ticket) && g_trade.ResultRetcode() == TRADE_RETCODE_DONE)
        {
         PrintFormat("[FUSION] %s 逆指値 #%I64u を取消（%s）", c.sym, ticket, why);
         if(partial)
            return FUS_CXL_FILLED;
         //--- 取消の直前に一部約定していないかを、履歴に入っていれば確かめる
         if(HistoryOrderSelect(ticket) &&
            HistoryOrderGetDouble(ticket, ORDER_VOLUME_INITIAL) - HistoryOrderGetDouble(ticket, ORDER_VOLUME_CURRENT) > 1e-10)
            return FUS_CXL_FILLED;
         return FUS_CXL_DONE;
        }
      uint rc = g_trade.ResultRetcode();
      if(OrderSelect(ticket))
        {
         c.real.lastRc = rc;
         if(rc == TRADE_RETCODE_MARKET_CLOSED)
            HoldMarket(c);
         else
            if(LogDue(c.real.logMs))
               PrintFormat("[FUSION] %s 逆指値 #%I64u の取消に失敗（%u %s）。再試行します（%s）", c.sym, ticket,
                           rc, g_trade.ResultRetcodeDescription(), why);
         return FUS_CXL_FAIL;
        }
     }
   return OrderOutcome(ticket);
  }

//--- 消えた注文の結果を確かめる準備（追っていた注文か、記録にある注文なら key も分かる）
void NoteVanished(CSymbolCtx *c, const ulong t)
  {
   if(c.real.chkTicket != 0 && c.real.chkTicket != t)
      PrintFormat("[FUSION] %s 注文 #%I64u の結果は、建玉の引き継ぎ（コメント）で確かめます", c.sym, c.real.chkTicket);
   if(t == c.real.ordTicket)
     {
      c.real.SetChk(t, c.real.ordDir, c.real.ordKeyTime, c.real.ordPrice, c.real.ordSetup.score);
      return;
     }
   int ri = c.real.FindRec(t);
   if(ri >= 0)
      c.real.SetChk(t, c.real.recDir[ri], c.real.recKeyTime[ri], c.real.recPlanned[ri], c.real.recScore[ri]);
   else
      c.real.SetChk(t, 0, 0, 0.0, 0);
  }

//--- この銘柄の自分の待機注文を取消す（keep は残す）。戻り値は取消せずに残った数（あとで再試行）
int CancelOwnOrders(CSymbolCtx *c, const ulong keep, const string why)
  {
   int left = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0 || t == keep)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != c.sym || OrderGetInteger(ORDER_MAGIC) != InpMagicNumber)
         continue;
      int r = CancelTicket(c, t, why);
      if(r == FUS_CXL_FAIL)
        {
         left++;
         continue;
        }
      if(r != FUS_CXL_DONE)
         NoteVanished(c, t);                    // 約定していた（かもしれない）：結果を確かめてから次へ進む
      if(t == c.real.ordTicket)
         c.real.ClearOrder();
     }
   return left;
  }

//--- 結果待ちの注文を履歴で確かめる。約定なら約定済み集合に入れ、建玉の確認（fill）に回す
bool ResolveChk(CSymbolCtx *c)
  {
   ulong t = c.real.chkTicket;
   int r = OrderOutcome(t);
   if(r == FUS_CXL_FAIL)
      return false;                              // まだ有効（成行の処理中など）
   if(r == FUS_CXL_UNKNOWN)
     {
      if(NowMs() - c.real.chkSinceMs < FUS_CHK_WAIT_MS)
         return false;
      PrintFormat("[FUSION] %s 注文 #%I64u の結果を履歴で確かめられません。約定していれば建玉の引き継ぎ（コメント）で拾います。この足では置き直しません", c.sym, t);
      c.real.want = false;                       // 約定していたかもしれない：同じセットアップに入り直さない（次の確定足で判定し直す）
      c.real.cancelMsg = "";
      c.real.ClearChk();
      return true;
     }
   if(r == FUS_CXL_FILLED)
     {
      //--- key の分からない注文（記録になく、コメントもまだ読んでいない）は、注文のコメントから読む
      if(c.real.chkKeyTime <= 0)
        {
         int kd = 0;
         datetime kt = 0;
         if(ParseRealComment(HistoryOrderGetString(t, ORDER_COMMENT), kd, kt))
           {
            c.real.chkDir = kd;
            c.real.chkKeyTime = kt;
           }
        }
      int ki = (c.real.chkKeyTime > 0) ? c.eng.IndexOfTime(c.real.chkKeyTime) : -1;
      if(c.real.chkDir != 0 && ki >= 0)
         c.real.cons.Add(c.real.chkDir, ki);    // 1セットアップにつき約定1回（R06）
      //--- 約定で待機注文を使い切った。Python も足の途中では新しく置かない（次の確定足で、約定済み集合で判定し直す）
      c.real.want = false;
      c.real.cancelMsg = "";
      c.real.cancelReq = true;                   // 部分約定の残りなど、残っている自分の待機注文はすべて取消す
      long pid = HistoryOrderGetInteger(t, ORDER_POSITION_ID);
      if(pid == 0)
         pid = (long)t;
      if(c.real.posTicket != 0 && pid == c.real.posId)
         PrintFormat("[FUSION] %s 注文 #%I64u の約定を確かめた（建玉 #%I64u として追跡中）", c.sym, t, c.real.posTicket);
      else
         if(c.real.Recorded(pid))
            PrintFormat("[FUSION] %s 注文 #%I64u の約定を確かめた（建玉 ID %I64d は記録済み）", c.sym, t, pid);
         else
           {
            c.real.fillPosId = pid;              // 建玉が見えるか、約定してすぐ閉じたことを履歴で確かめる
            c.real.fillDir = c.real.chkDir;
            c.real.fillKeyTime = c.real.chkKeyTime;
            c.real.fillPlanned = c.real.chkPlanned;
            c.real.fillScore = c.real.chkScore;
            c.real.fillSinceMs = NowMs();
           }
     }
   else
     {
      long st = HistoryOrderGetInteger(t, ORDER_STATE);
      if(st == ORDER_STATE_EXPIRED)
         PrintFormat("[FUSION] %s 逆指値 #%I64u が失効した（DAY）。置き直します", c.sym, t);
      else
         if(st == ORDER_STATE_REJECTED)
            PrintFormat("[FUSION] %s 注文 #%I64u は拒否された", c.sym, t);
         else
            if(st == ORDER_STATE_CANCELED)
               PrintFormat("[FUSION] %s 注文 #%I64u は約定せずに取消された。条件が続いていれば置き直します", c.sym, t);
      c.real.tryMs = 0;
     }
   c.real.ClearChk();
   return true;
  }

//--- 約定の理由（DEAL_REASON）→ 決済理由の名前
string DealReasonText(const long dreason, const bool trailed)
  {
   if(dreason == DEAL_REASON_SL)
      return trailed ? "TRAIL" : "SL";
   if(dreason == DEAL_REASON_SO)
      return "STOPOUT";
   if(dreason == DEAL_REASON_TP)
      return "TP";
   if(dreason == DEAL_REASON_CLIENT || dreason == DEAL_REASON_MOBILE || dreason == DEAL_REASON_WEB)
      return "MANUAL";
   if(dreason == DEAL_REASON_EXPERT)
      return "EXPERT";
   return "OTHER";
  }

void AddRealStats(CSymbolCtx *c, const double r)
  {
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
  }

//--- 新しく見つけた建玉を追う（選択済みの建玉）。この EA が出した注文の約定なら通知し、そうでなければ引き継ぐ
void TrackNewPosition(CSymbolCtx *c, const ulong tk)
  {
   long pid = PositionGetInteger(POSITION_IDENTIFIER);
   int dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
   c.real.ClearPosition();
   c.real.posTicket = tk;
   c.real.posId = pid;
   c.real.posDir = dir;
   c.real.posTime = (datetime)PositionGetInteger(POSITION_TIME);
   c.real.posEntry = PositionGetDouble(POSITION_PRICE_OPEN);
   c.real.posSl = PositionGetDouble(POSITION_SL);
   c.real.posVolume = PositionGetDouble(POSITION_VOLUME);
   c.real.posEntryIdx = c.eng.IndexOfBarContaining(c.real.posTime);
   //--- key・計画価格・スコア：この EA が出した注文なら記録から、なければ注文コメントから
   int ri = c.real.FindRec((ulong)pid);
   bool ours = (ri >= 0 || c.real.fillPosId == pid);
   datetime kt = 0;
   if(ri >= 0)
     {
      kt = c.real.recKeyTime[ri];
      c.real.posPlanned = c.real.recPlanned[ri];
      c.real.posScore = c.real.recScore[ri];
     }
   else
      if(c.real.fillPosId == pid)
        {
         kt = c.real.fillKeyTime;
         c.real.posPlanned = c.real.fillPlanned;
         c.real.posScore = c.real.fillScore;
        }
      else
        {
         int kd = 0;
         if(!ParseRealComment(PositionGetString(POSITION_COMMENT), kd, kt) || kd != dir)
            kt = 0;
        }
   if(c.real.fillPosId == pid)
      c.real.ClearFill();
   c.real.posKeyTime = kt;
   int ki = (kt > 0) ? c.eng.IndexOfTime(kt) : -1;
   if(ki >= 0)
      c.real.cons.Add(dir, ki);
   string gv = GvIsl(c, pid);
   if(ours)
     {
      c.real.posInitSl = c.real.posSl;
      GlobalVariableSet(gv, c.real.posInitSl);
      GlobalVariablesFlush();
      c.nfHas = false;
      string plan = "";
      if(c.real.posPlanned > 0.0)
         plan = StringFormat("（計画%s 差%+.0fポイント）", Px(c, c.real.posPlanned), (c.real.posEntry - c.real.posPlanned) * dir / c.point);
      Notify(StringFormat("%s %s %s 約定%s %s%s SL%s R=%.1fpips key %s", ModeTag(), c.sym, DirName(dir),
                          ((ulong)pid == c.real.mktTicket) ? "（成行）" : "", Px(c, c.real.posEntry), plan,
                          Px(c, c.real.posSl), MathAbs(c.real.posEntry - c.real.posInitSl) / c.pip, (kt > 0) ? FE_Time(kt) : "不明"), 1);
     }
   else
     {
      c.real.posInitSl = GlobalVariableCheck(gv) ? GlobalVariableGet(gv) : c.real.posSl;
      PrintFormat("[FUSION] %s 建玉 #%I64u を引き継ぎ（%s %s SL%s 初期SL%s key %s）", c.sym, tk, DirName(dir), Px(c, c.real.posEntry),
                  Px(c, c.real.posSl), Px(c, c.real.posInitSl), (kt > 0) ? FE_Time(kt) : "不明");
      c.real.missCheck = true;                  // 停止・切断の間に決済足や休場明けを過ぎていれば決済する
     }
   //--- 1銘柄1建玉：残っている自分の待機注文（部分約定の残りを含む）はすべて取消す
   c.real.want = false;
   c.real.cancelReq = true;
   g_panelDirty = true;
  }

//--- 決済の理由の名前。EA が送った決済（DEAL_REASON_EXPERT）なら、決済を要求した理由（週末・休場明け・トレール先の越え）。
//    決済を送る前後に SL・ストップアウトなどで閉じていれば、約定の理由（SL・TRAIL・STOPOUT など）
string ExitReasonText(const long dreason, const int closeReq, const bool trailed)
  {
   if(dreason == DEAL_REASON_EXPERT && closeReq != 0)
      return FE_ReasonName(closeReq);
   return DealReasonText(dreason, trailed);
  }

//--- 追っていた建玉が消えた：決済の約定から価格・理由・損益を拾って記録する。記録したら true
bool RecordExit(CSymbolCtx *c)
  {
   if(c.real.Recorded(c.real.posId))
     {
      //--- 同じ建玉を別の経路（約定してすぐ閉じた記録）ですでに記録した
      if(c.real.fillPosId == c.real.posId)
         c.real.ClearFill();
      c.real.ClearPosition();
      g_panelDirty = true;
      return true;
     }
   if(c.real.goneSinceMs == 0)
      c.real.goneSinceMs = NowMs();
   double exitPx = 0.0, profit = 0.0, swap = 0.0, comm = 0.0;
   datetime exitT = 0;
   long dreason = -1;
   bool found = false;
   if(HistorySelectByPosition(c.real.posId))
     {
      int nd = HistoryDealsTotal();
      for(int i = 0; i < nd; i++)
        {
         ulong dt = HistoryDealGetTicket(i);
         if(dt == 0)
            continue;
         profit += HistoryDealGetDouble(dt, DEAL_PROFIT);
         swap += HistoryDealGetDouble(dt, DEAL_SWAP);
         comm += HistoryDealGetDouble(dt, DEAL_COMMISSION);
         long et = HistoryDealGetInteger(dt, DEAL_ENTRY);
         if(et == DEAL_ENTRY_OUT || et == DEAL_ENTRY_OUT_BY || et == DEAL_ENTRY_INOUT)
           {
            exitPx = HistoryDealGetDouble(dt, DEAL_PRICE);
            exitT = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
            dreason = HistoryDealGetInteger(dt, DEAL_REASON);
            found = true;
           }
        }
     }
   if(!found && NowMs() - c.real.goneSinceMs < FUS_DEAL_WAIT_MS)
      return false;                              // 決済の約定が履歴に入るのを待つ（次の巡回で探し直す）
   string why = "UNKNOWN";
   if(found)
      why = ExitReasonText(dreason, c.real.closeReason, MathAbs(c.real.posSl - c.real.posInitSl) >= 0.5 * c.point);
   else
      if(c.real.closeReason != 0)
         why = FE_ReasonName(c.real.closeReason);
   double risk = MathAbs(c.real.posEntry - c.real.posInitSl);
   double r = (risk > 0.0 && exitPx > 0.0) ? (exitPx - c.real.posEntry) * c.real.posDir / risk : 0.0;
   AddRealStats(c, r);
   WriteRealTrade(c, c.real.posTime, c.real.posDir, c.real.posEntry, c.real.posInitSl, found ? exitT : NowServer(), why, r,
                  c.real.posKeyTime, c.real.posScore, c.real.posTicket, exitPx, c.real.posVolume, c.real.posPlanned, profit, swap, comm);
   c.real.MarkRecorded(c.real.posId);
   if(found)
      Notify(StringFormat("%s %s %s 決済 %s %s %+.2fR", ModeTag(), c.sym, DirName(c.real.posDir), why, Px(c, exitPx), r), 1);
   else
      Notify(StringFormat("%s %s %s 建玉がなくなったが、決済の約定を履歴で確かめられない（口座の履歴を確認してください）", ModeTag(), c.sym,
                          DirName(c.real.posDir)), 1);
   GlobalVariableDel(GvIsl(c, c.real.posId));
   if(c.real.fillPosId == c.real.posId)
      c.real.ClearFill();                        // 同じ建玉を「約定してすぐ閉じた」としてもう一度記録しない
   c.real.ClearPosition();
   g_panelDirty = true;
   return true;
  }

//--- 閉じた建玉（建玉 ID）を約定履歴から記録する（建玉を追わないまま閉じた場合）。
//    約定してすぐ閉じた（flash=true）と、追っていない建玉をこの EA が決済した（closeReq=決済を要求した理由）に使う。
//    記録した・記録済みだった・あきらめたら true（false は履歴に入るのを待つ）
bool RecordClosed(CSymbolCtx *c, const long pid, const int dirHint, const datetime keyHint, const int score, const double planned,
                  const uint sinceMs, const int closeReq, const bool flash)
  {
   if(c.real.Recorded(pid))
      return true;
   double entryPx = 0.0, exitPx = 0.0, vol = 0.0, profit = 0.0, swap = 0.0, comm = 0.0;
   datetime entryT = 0, exitT = 0;
   long dreason = -1;
   int d = dirHint;
   bool gotIn = false, gotOut = false;
   if(HistorySelectByPosition(pid))
     {
      int nd = HistoryDealsTotal();
      for(int i = 0; i < nd; i++)
        {
         ulong dt = HistoryDealGetTicket(i);
         if(dt == 0)
            continue;
         profit += HistoryDealGetDouble(dt, DEAL_PROFIT);
         swap += HistoryDealGetDouble(dt, DEAL_SWAP);
         comm += HistoryDealGetDouble(dt, DEAL_COMMISSION);
         long et = HistoryDealGetInteger(dt, DEAL_ENTRY);
         if(et == DEAL_ENTRY_IN && !gotIn)
           {
            entryPx = HistoryDealGetDouble(dt, DEAL_PRICE);
            entryT = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
            vol = HistoryDealGetDouble(dt, DEAL_VOLUME);
            d = (HistoryDealGetInteger(dt, DEAL_TYPE) == DEAL_TYPE_BUY) ? 1 : -1;
            gotIn = true;
           }
         if(et == DEAL_ENTRY_OUT || et == DEAL_ENTRY_OUT_BY || et == DEAL_ENTRY_INOUT)
           {
            exitPx = HistoryDealGetDouble(dt, DEAL_PRICE);
            exitT = (datetime)HistoryDealGetInteger(dt, DEAL_TIME);
            dreason = HistoryDealGetInteger(dt, DEAL_REASON);
            gotOut = true;
           }
        }
     }
   if(!(gotIn && gotOut))
     {
      if(NowMs() - sinceMs < FUS_DEAL_WAIT_MS)
         return false;                           // 建玉が見えるか、決済の約定が入るのを待つ
      if(flash)
         PrintFormat("[FUSION] %s 約定した注文の建玉（ID %I64d）を%s", c.sym, pid, gotIn ? "追えません（まだ開いていれば引き継ぎで拾います）" : "履歴で見つけられません");
      else
         Notify(StringFormat("%s %s 追っていなかった建玉（ID %I64d）を決済したが、約定を履歴で確かめられない（口座の履歴を確認してください）",
                             ModeTag(), c.sym, pid), 1);
      return true;
     }
   //--- 初期 SL は約定した注文の SL（建玉 ID＝約定した注文の番号）。key が分からなければ注文のコメントから読む
   double initSl = 0.0;
   datetime kt = keyHint;
   if(HistoryOrderSelect((ulong)pid))
     {
      initSl = HistoryOrderGetDouble((ulong)pid, ORDER_SL);
      int kd = 0;
      datetime kc = 0;
      if(kt <= 0 && ParseRealComment(HistoryOrderGetString((ulong)pid, ORDER_COMMENT), kd, kc) && kd == d)
         kt = kc;
     }
   int ki = (kt > 0) ? c.eng.IndexOfTime(kt) : -1;
   if(ki >= 0)
      c.real.cons.Add(d, ki);                    // 1セットアップにつき約定1回（R06）
   double risk = MathAbs(entryPx - initSl);
   double r = (risk > 0.0 && initSl > 0.0) ? (exitPx - entryPx) * d / risk : 0.0;
   string why = ExitReasonText(dreason, closeReq, false);
   AddRealStats(c, r);
   WriteRealTrade(c, entryT, d, entryPx, initSl, exitT, why, r, kt, score, (ulong)pid, exitPx, vol, planned, profit, swap, comm);
   c.real.MarkRecorded(pid);
   GlobalVariableDel(GvIsl(c, pid));
   if(flash)
      Notify(StringFormat("%s %s %s 約定 %s→すぐ決済 %s %s %+.2fR key %s", ModeTag(), c.sym, DirName(d), Px(c, entryPx), why, Px(c, exitPx), r,
                          (kt > 0) ? FE_Time(kt) : "不明"), 1);
   else
      Notify(StringFormat("%s %s %s 決済 %s %s %+.2fR（追っていなかった建玉 ID %I64d）", ModeTag(), c.sym, DirName(d), why, Px(c, exitPx), r, pid), 1);
   g_panelDirty = true;
   return true;
  }

//--- 約定を確かめたのに建玉が見えない：約定してすぐ閉じたなら、約定と決済をまとめて記録する
bool RecordFlash(CSymbolCtx *c)
  {
   if(!RecordClosed(c, c.real.fillPosId, c.real.fillDir, c.real.fillKeyTime, c.real.fillScore, c.real.fillPlanned,
                    c.real.fillSinceMs, 0, true))
      return false;
   c.real.ClearFill();
   g_panelDirty = true;
   return true;
  }

//--- 追っていない建玉をこの EA が決済した：約定履歴から記録するまで覚える
void AddOrphan(CSymbolCtx *c, const long pid, const int closeReq)
  {
   if(pid == 0 || c.real.Recorded(pid))
      return;
   int slot = -1;
   for(int i = 0; i < FUS_ORPHANS; i++)
     {
      if(c.real.orphPid[i] == pid)
         return;
      if(slot < 0 && c.real.orphPid[i] == 0)
         slot = i;
     }
   if(slot < 0)
     {
      PrintFormat("[FUSION] %s 決済した建玉（ID %I64d）の記録待ちが多すぎるため、記録しません", c.sym, pid);
      return;
     }
   c.real.orphPid[slot] = pid;
   c.real.orphReq[slot] = closeReq;
   c.real.orphSinceMs[slot] = NowMs();
  }

//--- 記録待ちの決済（追っていなかった建玉）を約定履歴から記録する
bool ServiceOrphans(CSymbolCtx *c)
  {
   bool changed = false;
   for(int i = 0; i < FUS_ORPHANS; i++)
     {
      long pid = c.real.orphPid[i];
      if(pid == 0)
         continue;
      if(RecordClosed(c, pid, 0, 0, 0, 0.0, c.real.orphSinceMs[i], c.real.orphReq[i], false))
        {
         c.real.orphPid[i] = 0;
         changed = true;
        }
     }
   return changed;
  }

//--- 実際の注文・建玉の変化を拾う（約定・決済の検出）。変化があれば true
bool RealReconcile(CSymbolCtx *c)
  {
   bool changed = false;
   //--- 1) 追っていた逆指値が消えた：約定か取消か失効かを履歴で確かめる
   if(c.real.ordTicket != 0 && !OrderSelect(c.real.ordTicket))
     {
      NoteVanished(c, c.real.ordTicket);
      c.real.ClearOrder();
      changed = true;
     }
   //--- 2) 結果待ちの注文
   if(c.real.chkTicket != 0 && ResolveChk(c))
      changed = true;
   //--- 3) 建玉（自分の建玉が2本以上あれば、追っている建玉がまだあればそれを追い続け、異常として知らせる）
   ulong tk = 0;
   bool has = FindPosition(c.sym, tk);
   if(has && c.real.posTicket != 0 && tk != c.real.posTicket && PositionSelectByTicket(c.real.posTicket))
      tk = c.real.posTicket;
   int npos = has ? CountOwnPositions(c.sym) : 0;
   if(npos > 1)
     {
      if(!c.real.multiWarned)
        {
         c.real.multiWarned = true;
         Notify(StringFormat("%s %s 【要対応】この EA の建玉が %d 本あります（1銘柄1建玉のはず）。追っている1本だけをトレールします。ほかは手動で整理してください（週末・休場明けの決済は全部に行う）",
                             ModeTag(), c.sym, npos), 1);
        }
     }
   else
      c.real.multiWarned = false;
   if(has && PositionSelectByTicket(tk))
     {
      if(c.real.posTicket == tk)
        {
         c.real.posSl = PositionGetDouble(POSITION_SL);
         c.real.posVolume = PositionGetDouble(POSITION_VOLUME);
         if(c.real.fillPosId != 0 && c.real.fillPosId == c.real.posId)
            c.real.ClearFill();
        }
      else
        {
         if(c.real.posTicket != 0 && !RecordExit(c))
            return changed;                      // 前の建玉の決済を記録してから新しい建玉を追う
         if(PositionSelectByTicket(tk))
           {
            TrackNewPosition(c, tk);
            changed = true;
           }
        }
     }
   else
     {
      if(c.real.posTicket != 0)
        {
         if(RecordExit(c))
            changed = true;
        }
      else
         if(c.real.fillPosId != 0 && RecordFlash(c))
            changed = true;
     }
   return changed;
  }

//--- 決済の要求（建玉が消えるまで ServiceClose が再試行する）
void RequestClose(CSymbolCtx *c, const int reason, const string why)
  {
   if(c.real.closeReq != 0)
      return;
   c.real.closeReq = reason;
   c.real.closeSinceMs = NowMs();
   c.real.closeTryMs = 0;
   c.real.closeWaitMs = FUS_RETRY_MS;
   c.real.closeFails = 0;
   c.real.closeWarned = false;
   c.real.closeWarned2 = false;
   c.real.holdNoted = false;
   c.real.want = false;
   c.real.cancelReq = true;
   c.real.trailSl = 0.0;
   PrintFormat("[FUSION] %s 建玉を決済します（%s）", c.sym, why);
  }

//--- 建玉を1つ成行で決済する（再クオート・価格変更なら取り直して最大3回）。戻り値 FUS_CLOSE_*。rc は最後の戻りコード
int ClosePositionTicket(CSymbolCtx *c, const ulong tk, string &err, uint &rc)
  {
   err = "";
   rc = 0;
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(!PositionSelectByTicket(tk))
         return FUS_CLOSE_GONE;                  // もう建玉がない（SL などで閉じた）
      g_trade.SetTypeFillingBySymbol(c.sym);
      bool ok = g_trade.PositionClose(tk);
      rc = g_trade.ResultRetcode();
      if(ok && rc == TRADE_RETCODE_DONE)
         return FUS_CLOSE_DONE;
      err = StringFormat("%u %s", rc, g_trade.ResultRetcodeDescription());
      if(!PositionSelectByTicket(tk))
         return (ok && rc == TRADE_RETCODE_DONE_PARTIAL) ? FUS_CLOSE_DONE : FUS_CLOSE_GONE;
      if(ok && rc == TRADE_RETCODE_DONE_PARTIAL)
         continue;                               // 一部だけ決済：残りを続けて決済
      if(!(rc == TRADE_RETCODE_REQUOTE || rc == TRADE_RETCODE_PRICE_CHANGED || rc == TRADE_RETCODE_PRICE_OFF))
         break;
     }
   return FUS_CLOSE_FAIL;
  }

//--- 決済の要求の処理（読み直し中でも行う。足のデータを使わない）
bool ServiceClose(CSymbolCtx *c)
  {
   if(!HasOwnPosition(c.sym))
     {
      if(c.real.closeFails > 0)
         Notify(StringFormat("%s %s 決済できました（%d 回失敗の後）", ModeTag(), c.sym, c.real.closeFails), 1);
      c.real.closeReq = 0;
      return true;
     }
   uint now = NowMs();
   if(c.real.closeTryMs != 0 && now - c.real.closeTryMs < c.real.closeWaitMs)
      return false;
   if(MarketHeld(c))
      return false;                              // 市場が閉まっていた：新しいティックが来るまで送らない
   c.real.closeTryMs = now;
   string why = "";
   uint lastRc = 0;
   if(!CanTrade(c, 0, why))
     {
      c.real.closeFails++;
     }
   else
     {
      int left = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk == 0)
            continue;
         if(PositionGetString(POSITION_SYMBOL) != c.sym || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
            continue;
         long pid = PositionGetInteger(POSITION_IDENTIFIER);
         string err = "";
         uint rc = 0;
         int res = ClosePositionTicket(c, tk, err, rc);
         if(res == FUS_CLOSE_DONE)
           {
            if(tk == c.real.posTicket)
               c.real.closeReason = c.real.closeReq;   // この EA が決済したときだけ理由を残す
            else
               AddOrphan(c, pid, c.real.closeReq);     // 追っていなかった建玉：約定履歴から記録する
            PrintFormat("[FUSION] %s 建玉 #%I64u を決済（%s）", c.sym, tk, FE_ReasonName(c.real.closeReq));
           }
         else
            if(res == FUS_CLOSE_FAIL)
              {
               left++;
               why = err;
               lastRc = rc;
              }
        }
      if(left == 0)
        {
         c.real.closeWaitMs = FUS_RETRY_MS;
         return true;                            // 次の巡回で建玉が消えたことを確かめる
        }
      c.real.closeFails++;
     }
   if(lastRc == TRADE_RETCODE_MARKET_CLOSED)
     {
      //--- 市場が閉まっている（週末・休場）：手動でも決済できないので【要対応】は送らず、再開直後に決済する
      HoldMarket(c);
      c.real.closeWaitMs = FUS_RETRY_MS;
      c.real.closeSinceMs = now;                 // 「5分たっても決済できない」は、市場が開いてから数える
      if(!c.real.holdNoted)
        {
         c.real.holdNoted = true;
         Notify(StringFormat("%s %s %s の決済: 市場が閉まっているため、取引が再開したらすぐ決済します", ModeTag(), c.sym,
                             FE_ReasonName(c.real.closeReq)), 1);
        }
      return true;
     }
   c.real.closeWaitMs = FailDelayMs(lastRc, c.real.closeFails);
   if(LogDue(c.real.logMs))
      PrintFormat("[FUSION] %s 建玉の決済に失敗（%s）。%d 秒後に再試行します（失敗 %d 回）", c.sym, why, (int)(c.real.closeWaitMs / 1000), c.real.closeFails);
   if(!c.real.closeWarned)
     {
      c.real.closeWarned = true;
      Notify(StringFormat("%s %s 【要対応】%s の決済に失敗（%s）。再試行中。必要なら手動で決済してください", ModeTag(), c.sym,
                          FE_ReasonName(c.real.closeReq), why), 1);
     }
   else
      if(!c.real.closeWarned2 && now - c.real.closeSinceMs >= FUS_CLOSE_WARN2_MS)
        {
         c.real.closeWarned2 = true;
         Notify(StringFormat("%s %s 【要対応】5分たっても決済できません（%s）。手動で決済してください", ModeTag(), c.sym, why), 1);
        }
   return true;
  }

//--- 自分の待機注文をすべて取消す要求の処理（読み直し中でも行う）
bool ServiceCancel(CSymbolCtx *c)
  {
   uint now = NowMs();
   if(c.real.cxlTryMs != 0 && now - c.real.cxlTryMs < c.real.cxlWaitMs)
      return false;
   if(MarketHeld(c))
      return false;
   c.real.lastRc = 0;
   int left = CancelOwnOrders(c, 0, "建玉あり・決済・休場明け");
   if(left == 0)
     {
      c.real.cancelReq = false;
      c.real.cxlTryMs = 0;
      c.real.cxlFails = 0;
      c.real.cxlWaitMs = FUS_RETRY_MS;
     }
   else
     {
      c.real.cxlTryMs = now;
      c.real.cxlFails++;
      c.real.cxlWaitMs = FailDelayMs(c.real.lastRc, c.real.cxlFails);
     }
   return true;
  }

//--- 決済足の終わりが近いか（建玉があり、形成中の足が決済足で、終わりの FUS_PRECLOSE_SEC 秒前を過ぎた）。
//    Python は決済足の終値で決済する。市場がその足の終わりで閉じる日（早仕舞い・休場前）でも決済できるよう、
//    実建玉は足の終わりの少し前に決済する（次の足の最初のティックを待たない）
bool PreCloseDue(CSymbolCtx *c)
  {
   if(!HasOwnPosition(c.sym))
      return false;
   datetime now = NowServer();
   datetime cur = (datetime)((long)now - (long)now % 3600);
   datetime ft = iTime(c.sym, PERIOD_H1, 0);
   if(ft > cur)
      cur = ft;
   if(c.eng.IsWeekendBar(cur))
      return false;
   bool nn = false, fl = false, rl = false;
   int kd = 0;
   c.eng.TimeRulesAt(cur, nn, fl, rl, kd);
   if(!fl)
      return false;
   return ((long)now >= (long)cur + 3600 - FUS_PRECLOSE_SEC);
  }

//--- 切断・停止の間（追いつき処理・起動・再接続での引き継ぎ）に、追っている建玉の約定より後で決済足が確定していた、
//    または休場明けを過ぎていたら、すぐ決済する（仮想側の Python はその足で WEEKEND・GAP_FALLBACK として閉じている）。
//    決済を要求したら true
bool CheckMissedClose(CSymbolCtx *c)
  {
   if(c.real.closeReq != 0 || c.real.posTicket == 0)
      return false;
   int n = c.eng.m_n;
   if(n <= 0 || c.eng.m_first < 0)
      return false;
   datetime pt = c.real.posTime;
   int e = c.eng.IndexOfBarContaining(pt);
   if(e >= n)
      return false;                              // 形成中の足で約定した（確定した決済足はまだない）
   if(e < 0)
      e = 0;                                     // 読み込んだ足より前からの建玉
   int reason = 0;
   datetime at = 0;
   for(int k = e; k < n; k++)
     {
      if(k > e && c.eng.GapBefore(c.eng.m_T[k - 1], c.eng.m_T[k]))
        {
         reason = XR_GAP;                         // 休場明けの足の始値で決済のはずだった
         at = c.eng.m_T[k];
         break;
        }
      bool nn = false, fl = false, rl = false;
      int kd = 0;
      c.eng.TimeRules(k, nn, fl, rl, kd);
      if(fl && (long)c.eng.m_T[k] + 3600 > (long)pt)
        {
         reason = XR_WEEKEND;                     // 決済足の終値で決済のはずだった
         at = (datetime)((long)c.eng.m_T[k] + 3600);
         break;
        }
     }
   if(reason == 0)
      return false;
   string what = (reason == XR_GAP) ? "休場明け" : "決済足の確定";
   Notify(StringFormat("%s %s %s 切断・停止の間に%s（%s）を過ぎた建玉を、いま成行で決済します", ModeTag(), c.sym,
                       DirName(c.real.posDir), what, FE_Time(at)), 1);
   RequestClose(c, reason, "切断・停止の間に" + what + "を過ぎた");
   return true;
  }

//--- 休場明け：建玉は成行で決済し、待機注文は取消す（形成中の足の最初のティック。SPEC §17.9）
void RealGapFallback(CSymbolCtx *c)
  {
   bool hadPos = HasOwnPosition(c.sym);
   int nOrd = CountOwnOrders(c.sym, 0);
   c.real.want = false;
   c.real.cancelMsg = "";
   c.real.trailSl = 0.0;
   if(nOrd > 0)
      c.real.cancelReq = true;
   if(hadPos)
      RequestClose(c, XR_GAP, "休場明け");
   if(hadPos || nOrd > 0)
      Notify(StringFormat("%s %s GAP_FALLBACK 休場明け（12時間以上の空き）: %s", ModeTag(), c.sym,
                          hadPos ? ((nOrd > 0) ? "建玉を成行で決済・逆指値を取消" : "建玉を成行で決済") : "逆指値を取消"), 1);
  }

//--- 自動売買の巡回（全銘柄・毎回）。変化があれば true
bool RealService(CSymbolCtx *c)
  {
   if(!TradeReady())
      return false;
   bool changed = false;
   CheckTradePermission(c);
   //--- 口座の引き継ぎと約定・決済の検出（足番号を使うので、準備済みのときだけ）
   if(c.ready)
     {
      if(!c.real.adopted)
        {
         RealAdopt(c);
         c.real.adopted = true;
         changed = true;
        }
      if(RealReconcile(c))
         changed = true;
      if(c.real.missCheck)
        {
         c.real.missCheck = false;
         if(CheckMissedClose(c))
            changed = true;
        }
     }
   //--- 休場明け・決済足の終わり・決済・取消（足のデータを使わないので、読み直し中でも行う）
   if(c.real.gapBar != 0)
     {
      RealGapFallback(c);
      c.real.gapBar = 0;
      changed = true;
     }
   if(c.real.closeReq == 0 && PreCloseDue(c))
      RequestClose(c, XR_WEEKEND, "決済足の終わり");
   if(c.real.closeReq != 0 && ServiceClose(c))
      changed = true;
   if(ServiceOrphans(c))
      changed = true;
   if(c.real.cancelReq && ServiceCancel(c))
      changed = true;
   if(!c.ready || !c.real.adopted)
      return changed;
   //--- 確定足の管理（run_h1 の 4〜6）と、置きたい注文・トレールに実際を合わせる
   if(c.real.barDue)
     {
      RealOnBar(c);
      c.real.barDue = false;
      changed = true;
     }
   if(RealApply(c))
      changed = true;
   return changed;
  }

//--- 足 k（最後の確定足）の確定時の判断（run_h1 の 4〜6 と同じ順）。実際の発注・取消は RealApply が行う
void RealOnBar(CSymbolCtx *c)
  {
   int k = c.eng.m_n - 1;
   if(c.eng.m_first < 0 || k < c.eng.m_first)
      return;
   bool no_new = false, flat = false, roll = false;
   int kind = 0;
   c.eng.TimeRules(k, no_new, flat, roll, kind);
   //--- 形成中の足が休場明けなら、直後のフォールバックで取消すので新しく置かない
   bool gapNext = (c.lastForming > c.eng.m_T[k] && !c.eng.IsWeekendBar(c.lastForming) && c.eng.GapBefore(c.eng.m_T[k], c.lastForming));
   bool pos = (c.real.posTicket != 0 || HasOwnPosition(c.sym));
   c.real.want = false;
   c.real.cancelMsg = "";
   c.real.tryMs = 0;
   c.real.tryWaitMs = FUS_RETRY_MS;
   c.real.tryFails = 0;
   c.real.mktTries = 0;
   c.real.trailSl = 0.0;
   c.real.trailTryMs = 0;
   c.real.trailWaitMs = FUS_RETRY_MS;
   c.real.trailFails = 0;
   //--- 4) 確定時の管理：決済足なら決済、そうでなければ構造トレール
   if(pos)
     {
      if(flat)
         RequestClose(c, XR_WEEKEND, "決済足");
      else
         if(c.real.posTicket != 0)
           {
            double newSl = 0.0, swp = 0.0;
            if(c.eng.TrailCandidate(k, c.real.posDir, c.real.posEntryIdx, c.real.posSl, newSl, swp))
              {
               c.real.trailSl = newSl;
               c.real.trailSw = swp;
              }
           }
     }
   if(flat)
     {
      c.real.prevNoNew = no_new;
      return;                                           // 待機注文は RealApply が取消す
     }
   //--- 5) 新規停止・ロールオーバー → 建玉あり（Python と同じ順。SPEC 付録E の E-13）
   bool edge = (no_new && !c.real.prevNoNew && kind >= 2);
   c.real.prevNoNew = no_new;
   if(no_new || roll)
     {
      if(no_new)
        {
         c.nfHas = false;                               // 週明けに置き直したら通知する
         if(edge)
           {
            datetime nyb = (datetime)((long)c.eng.m_T[k] - (long)InpServerOffsetHours * 3600);
            string why = (kind == 2) ? "早仕舞い日17時" : ((FE_DayOfWeek(nyb) == 5) ? "金曜20時" : "休場前日20時");
            Notify(StringFormat("%s %s 新規停止（%s）%s", ModeTag(), c.sym, why, (c.real.ordTicket != 0) ? " 逆指値を取消" : ""));
           }
        }
      return;
     }
   if(pos || gapNext)
      return;
   //--- 6) 新規判定（実際に約定した key の集合で）
   SSetup best;
   FE_SetupClear(best);
   bool has = c.eng.EvalBest(k, c.real.cons, best);
   if(!has)
     {
      if(c.real.ordTicket != 0)
        {
         int ic = c.eng.InvalidCode(c.real.ordDir, c.real.ordSetup.pattern);
         c.real.cancelMsg = StringFormat("%s %s %s 待機注文を取消 INVALID %s（%s） 逆指値%s", ModeTag(), c.sym, DirName(c.real.ordDir),
                                         FE_CodeName(ic), FE_CodeDesc(ic), Px(c, c.real.ordPrice));
        }
      return;
     }
   //--- スプレッド防御：3×s_nom を超える間は武装・修正しない（置いていた逆指値は取消して、次の足で評価し直す）
   double spread = SymbolInfoDouble(c.sym, SYMBOL_ASK) - SymbolInfoDouble(c.sym, SYMBOL_BID);
   if(spread > 3.0 * c.eng.m_p.s_nom)
     {
      PrintFormat("[FUSION] %s スプレッド %s が 3×s_nom を超えるため、この足は武装しない%s", c.sym, DoubleToString(spread, c.digits),
                  (c.real.ordTicket != 0) ? "（置いていた逆指値は取消す）" : "");
      if(c.real.ordTicket != 0)
         c.real.cancelMsg = StringFormat("%s %s %s 待機注文を取消（スプレッド %s が 3×s_nom を超えた。次の足で評価し直す） 逆指値%s",
                                         ModeTag(), c.sym, DirName(c.real.ordDir), DoubleToString(spread, c.digits), Px(c, c.real.ordPrice));
      return;
     }
   c.real.want = true;
   c.real.wantSetup = best;
  }

//--- 構造トレール（確定時に決めた SL を PositionModify）。置けたら・やめたら true（false はあとで再試行）
bool ApplyTrail(CSymbolCtx *c)
  {
   int d = c.real.posDir;
   c.real.lastRc = 0;
   if(!PositionSelectByTicket(c.real.posTicket))
      return true;                                      // 建玉がない（決済済み）
   double cur = PositionGetDouble(POSITION_SL);
   double nsl = NormalizeDouble(c.real.trailSl, c.digits);
   if(cur != 0.0 && (nsl - cur) * d <= 0)
      return true;                                      // すでに同じか先にある
   MqlTick tk;
   if(!SymbolInfoTick(c.sym, tk))
      return false;
   double px = (d == 1) ? tk.bid : tk.ask;
   //--- 価格がすでに新しい SL を越えている：Python ではこの足で SL に掛かる（始値なら SL_gap）→ 成行で決済
   if((px - nsl) * d <= 0)
     {
      RequestClose(c, XR_TRAIL, "トレール先 " + Px(c, nsl) + " を価格が越えていた");
      return true;
     }
   double stops = MinStopDist(c, tk.ask, tk.bid);
   if((px - nsl) * d <= stops)
     {
      if(LogDue(c.real.logMs))
         PrintFormat("[FUSION] %s トレール先 %s が現在値に近すぎる（STOPS_LEVEL）。離れたら置きます", c.sym, Px(c, nsl));
      return false;                                     // SPEC §17.7：new_SL < Bid − stops_level のときだけ
     }
   double freeze = FreezeDist(c);
   if(cur != 0.0 && freeze > 0.0 && (px - cur) * d < freeze)
     {
      if(LogDue(c.real.logMs))
         PrintFormat("[FUSION] %s いまの SL が FREEZE_LEVEL の内側のため、トレールを待ちます", c.sym);
      return false;
     }
   bool ok = g_trade.PositionModify(c.real.posTicket, nsl, 0.0);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_NO_CHANGES))
     {
      c.real.lastRc = rc;
      if(rc == TRADE_RETCODE_MARKET_CLOSED)
         HoldMarket(c);
      else
         if(LogDue(c.real.logMs))
            PrintFormat("[FUSION] %s SL の引上げに失敗（%u %s）。あとで再試行", c.sym, rc, g_trade.ResultRetcodeDescription());
      return false;
     }
   double old = c.real.posSl;
   c.real.posSl = nsl;
   Notify(StringFormat("%s %s %s SL引上げ %s→%s（4H%s %s）", ModeTag(), c.sym, DirName(d), Px(c, old), Px(c, nsl),
                       (d == 1) ? "押し安値" : "戻り高値", Px(c, c.real.trailSw)));
   return true;
  }

//--- 見送りの通知：同じ方向・key・理由の2回目からはログだけにする（同じセットアップが続く間、毎時同じ通知を送らない）
void NotifySkip(CSymbolCtx *c, const SSetup &s, const int code, const string msg)
  {
   if(c.real.skipDir == s.dir && c.real.skipKeyTime == s.key_time && c.real.skipCode == code)
     {
      Print(msg + "（同じセットアップ・同じ理由の2回目以降のため通知は省く）");
      return;
     }
   c.real.skipDir = s.dir;
   c.real.skipKeyTime = s.key_time;
   c.real.skipCode = code;
   Notify(msg);
  }

//--- 発注・修正・取消がまだできない：次の再試行までの間隔を、拒否の種類（c.real.lastRc）で決める
void RetryLater(CSymbolCtx *c, const uint now)
  {
   c.real.tryMs = now;
   c.real.tryFails++;
   c.real.tryWaitMs = FailDelayMs(c.real.lastRc, c.real.tryFails);
  }

void RetryReset(CSymbolCtx *c)
  {
   c.real.tryMs = 0;
   c.real.tryFails = 0;
   c.real.tryWaitMs = FUS_RETRY_MS;
  }

//--- 新しい逆指値（Ask がすでに price 以上なら成行。§7.5）。戻り値 1=置いた 2=成行を出した 0=あとで再試行 -1=この足は見送り。
//    拒否されたときは c.real.lastRc に戻りコードを残す（再試行の間隔を決める）
int RealPlaceOrder(CSymbolCtx *c, const SSetup &s)
  {
   string sym = c.sym;
   string why = "";
   c.real.lastRc = 0;
   //--- 最後の確認：約定済みのセットアップ（R06）には置かない。自分の建玉・待機注文が残っていれば置かない（二重の建玉を防ぐ）
   if(s.key_idx >= 0 && c.real.cons.Has(s.dir, s.key_idx))
     {
      PrintFormat("[FUSION] %s %s key %s は約定済み（R06）のため置きません", sym, DirName(s.dir), FE_Time(s.key_time));
      return -1;
     }
   if(HasOwnPosition(sym) || CountOwnOrders(sym, 0) > 0)
     {
      if(LogDue(c.real.logMs))
         PrintFormat("[FUSION] %s 自分の建玉か待機注文が残っているため、新しい注文は出しません（あとで確かめ直す）", sym);
      return 0;
     }
   if(!CanTrade(c, s.dir, why))
     {
      if(LogDue(c.real.logMs))
         PrintFormat("[FUSION] %s 発注できません（%s）", sym, why);
      return 0;
     }
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk) || tk.ask <= 0.0 || tk.bid <= 0.0)
      return 0;
   double price = NormalizeDouble(s.price, c.digits);
   double sl = NormalizeDouble(s.sl, c.digits);
   double minDist = MinStopDist(c, tk.ask, tk.bid);
   bool market = (s.dir == 1) ? (tk.ask >= price) : (tk.bid <= price);
   string cmt = RealComment(s.dir, s.key_time);
   double ratio = 1.0;
   double lots = 0.0;
   double px = price;
   if(market)
     {
      //--- すでに価格を越えている：足の始まりなら成行（Python の始値約定に当たる）。
      //    足の途中（再起動・再接続・置けなかった注文の再試行）で大きく越えていたら見送る
      px = (s.dir == 1) ? tk.ask : tk.bid;
      double over = (px - price) * s.dir;
      long since = (long)NowServer() - (long)c.lastForming;
      double tol = MathMax(InpDeviationPoints * c.point, 0.1 * s.atr);
      if(since > FUS_LATE_SEC && over > tol)
        {
         NotifySkip(c, s, FUS_SKIP_LATE, StringFormat("%s %s %s 見送り: 価格%sが逆指値%sを越えていた（足の始まりから%d分。成行は Python の始値約定と離れる）",
                                                       ModeTag(), sym, DirName(s.dir), Px(c, px), Px(c, price), (int)(since / 60)));
         return -1;
        }
      //--- 成行を受け付けた後に拒否される（約定しない）ことが続くときは、この足では見送る
      if(c.real.mktTries >= FUS_MKT_TRIES)
        {
         NotifySkip(c, s, FUS_SKIP_MARKET, StringFormat("%s %s %s 見送り: 成行を %d 回出したが約定しなかった（次の確定足で評価し直す）",
                                                         ModeTag(), sym, DirName(s.dir), c.real.mktTries));
         return -1;
        }
      if((s.dir == 1 && tk.bid - sl <= minDist) || (s.dir == -1 && sl - tk.ask <= minDist))
        {
         if(LogDue(c.real.logMs))
            PrintFormat("[FUSION] %s 成行の SL %s が STOPS_LEVEL の内側のため待ちます", sym, Px(c, sl));
         return 0;
        }
      lots = CalcLotSize(sym, MathAbs(px - sl), ratio);       // 実際に入る価格からの損切り幅で計算する
     }
   else
     {
      if((s.dir == 1 && (price - tk.ask <= minDist || price - sl <= minDist)) || (s.dir == -1 && (tk.bid - price <= minDist || sl - price <= minDist)))
        {
         if(LogDue(c.real.logMs))
            PrintFormat("[FUSION] %s 逆指値 %s が STOPS_LEVEL の内側のため置けません。同じ足の中で再試行します", sym, Px(c, price));
         return 0;
        }
      lots = CalcLotSize(sym, MathAbs(price - sl), ratio);
     }
   if(lots <= 0.0)
     {
      PrintFormat("[FUSION] %s ロットを計算できません（損切り幅 %s）", sym, DoubleToString(MathAbs(px - sl), c.digits));
      return -1;
     }
   if(ratio > 1.5)
     {
      NotifySkip(c, s, FUS_SKIP_RATIO, StringFormat("%s %s %s 見送り: 最小ロットでもリスクが目標の %.1f 倍になる（損切り幅 %.1fpips）",
                                                     ModeTag(), sym, DirName(s.dir), ratio, MathAbs(px - sl) / c.pip));
      return -1;
     }
   double margin = 0.0;
   ENUM_ORDER_TYPE mt = (s.dir == 1) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(OrderCalcMargin(mt, sym, lots, px, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      NotifySkip(c, s, FUS_SKIP_MARGIN, StringFormat("%s %s %s 見送り: 証拠金が足りない（必要 %.2f）", ModeTag(), sym, DirName(s.dir), margin));
      return -1;
     }
   bool ok = false;
   uint rc = 0;
   if(market)
     {
      c.real.mktTries++;
      for(int a = 0; a < 3; a++)
        {
         g_trade.SetTypeFillingBySymbol(sym);
         ok = (s.dir == 1) ? g_trade.Buy(lots, sym, 0.0, sl, 0.0, cmt) : g_trade.Sell(lots, sym, 0.0, sl, 0.0, cmt);
         rc = g_trade.ResultRetcode();
         if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_DONE_PARTIAL || rc == TRADE_RETCODE_PLACED))
            break;
         ok = false;
         if(!(rc == TRADE_RETCODE_REQUOTE || rc == TRADE_RETCODE_PRICE_CHANGED || rc == TRADE_RETCODE_PRICE_OFF))
            break;
        }
     }
   else
     {
      ENUM_ORDER_TYPE_TIME tt = OrderTimeType(sym);
      g_trade.SetTypeFillingBySymbol(sym);
      for(int b = 0; b < 2; b++)
        {
         if(s.dir == 1)
            ok = g_trade.BuyStop(lots, price, sym, sl, 0.0, tt, 0, cmt);
         else
            ok = g_trade.SellStop(lots, price, sym, sl, 0.0, tt, 0, cmt);
         rc = g_trade.ResultRetcode();
         if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
            break;
         ok = false;
         if(rc != TRADE_RETCODE_INVALID_FILL)
            break;
         g_trade.SetTypeFilling(ORDER_FILLING_RETURN);        // 待機注文に FOK/IOC を受け付けないブローカー
        }
     }
   if(!ok)
     {
      c.real.lastRc = rc;
      if(rc == TRADE_RETCODE_MARKET_CLOSED)
         HoldMarket(c);
      else
         if(LogDue(c.real.logMs))
            PrintFormat("[FUSION] %s 発注失敗（%u %s）。あとで再試行", sym, rc, g_trade.ResultRetcodeDescription());
      return 0;
     }
   ulong ot = g_trade.ResultOrder();
   c.real.Remember(ot, s.dir, s.key_time, price, s.score);
   if(market)
     {
      //--- 成行は、約定を確かめてから「約定（成行）」として通知する（受け付けた後に拒否されたら通知しない）
      c.real.mktTicket = ot;
      c.real.SetChk(ot, s.dir, s.key_time, price, s.score);   // 約定を履歴で確かめ、約定済み集合に入れる
      Print(MsgArmed(c, s, "成行 ") + "（約定を確かめてから通知する）");
      return 2;
     }
   c.real.ordTicket = ot;
   c.real.ordDir = s.dir;
   c.real.ordKeyTime = s.key_time;
   c.real.ordPrice = price;
   c.real.ordSl = sl;
   c.real.ordSetup = s;
   bool newKey = (!c.nfHas || c.nfDir != s.dir || c.nfKeyTime != s.key_time);
   if(newKey || MathAbs(price - c.nfPrice) > 0.2 * s.atr || MathAbs(sl - c.nfSl) > 0.2 * s.atr)
     {
      c.nfHas = true;
      c.nfDir = s.dir;
      c.nfKeyTime = s.key_time;
      c.nfPrice = price;
      c.nfSl = sl;
      Notify(MsgArmed(c, s, newKey ? "" : "修正 "));
     }
   else
      PrintFormat("[FUSION] %s 逆指値を置き直し %s SL%s（同じ key）", sym, Px(c, price), Px(c, sl));
   return 1;
  }

//--- 同じ key：price・SL を今回の値に置き直す（OrderModify）。戻り値 1=済み 0=あとで再試行 -1=この足は見送り
int RealModifyOrder(CSymbolCtx *c, const SSetup &s)
  {
   string sym = c.sym;
   double price = NormalizeDouble(s.price, c.digits);
   double sl = NormalizeDouble(s.sl, c.digits);
   c.real.ordSetup = s;
   c.real.lastRc = 0;
   if(price == c.real.ordPrice && sl == c.real.ordSl)
      return 1;
   MqlTick tk;
   if(!SymbolInfoTick(sym, tk) || tk.ask <= 0.0 || tk.bid <= 0.0)
      return 0;
   if((s.dir == 1 && tk.ask >= price) || (s.dir == -1 && tk.bid <= price))
     {
      //--- 新しい価格をすでに越えている：取消して成行（Python の始値約定に当たる）
      ulong old = c.real.ordTicket;
      int r = CancelTicket(c, old, "価格を越えたので成行へ");
      if(r == FUS_CXL_FAIL)
         return 0;
      if(r != FUS_CXL_DONE)
        {
         NoteVanished(c, old);                    // 取消の前に約定（一部約定）していた：二重に入らない
         c.real.ClearOrder();
         return 1;
        }
      c.real.ClearOrder();
      return RealPlaceOrder(c, s);
     }
   double minDist = MinStopDist(c, tk.ask, tk.bid);
   double freeze = FreezeDist(c);
   double dist = (s.dir == 1) ? price - tk.ask : tk.bid - price;
   double curDist = (s.dir == 1) ? c.real.ordPrice - tk.ask : tk.bid - c.real.ordPrice;
   if(dist <= minDist || MathAbs(price - sl) <= minDist || (freeze > 0.0 && curDist < freeze))
     {
      if(LogDue(c.real.logMs))
         PrintFormat("[FUSION] %s 逆指値の修正は STOPS_LEVEL/FREEZE_LEVEL の内側のため待ちます（前の注文は残す）", sym);
      return 0;
     }
   bool ok = g_trade.OrderModify(c.real.ordTicket, price, sl, 0.0, OrderTimeType(sym), 0, 0.0);
   uint rc = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_NO_CHANGES))
     {
      c.real.lastRc = rc;
      if(rc == TRADE_RETCODE_MARKET_CLOSED)
         HoldMarket(c);
      else
         if(LogDue(c.real.logMs))
            PrintFormat("[FUSION] %s 逆指値の修正に失敗（%u %s）。前の注文を残して、あとで再試行", sym, rc, g_trade.ResultRetcodeDescription());
      return 0;
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
   return 1;
  }

//--- 置きたい注文・トレールに実際を合わせる（できなければ、拒否の種類で決めた間隔で再試行）。変化があれば true
bool RealApply(CSymbolCtx *c)
  {
   bool changed = false;
   uint now = NowMs();
   //--- トレール
   if(c.real.trailSl != 0.0)
     {
      if(c.real.posTicket == 0 || c.real.closeReq != 0)
         c.real.trailSl = 0.0;
      else
         if((c.real.trailTryMs == 0 || now - c.real.trailTryMs >= c.real.trailWaitMs) && !MarketHeld(c))
           {
            c.real.trailTryMs = now;
            if(ApplyTrail(c))
              {
               c.real.trailSl = 0.0;
               c.real.trailTryMs = 0;
               c.real.trailFails = 0;
               c.real.trailWaitMs = FUS_RETRY_MS;
               changed = true;
              }
            else
              {
               c.real.trailFails++;
               c.real.trailWaitMs = FailDelayMs(c.real.lastRc, c.real.trailFails);
              }
           }
     }
   //--- 注文（前の注文の結果待ち・決済中・全取消中・市場が閉まっていた間は動かさない）
   if(c.real.chkTicket != 0 || c.real.fillPosId != 0 || c.real.cancelReq || c.real.closeReq != 0)
      return changed;
   if(c.real.tryMs != 0 && now - c.real.tryMs < c.real.tryWaitMs)
      return changed;
   if(MarketHeld(c))
      return changed;
   c.real.lastRc = 0;
   bool posNow = (c.real.posTicket != 0 || HasOwnPosition(c.sym));
   if(posNow || !c.real.want)
     {
      if(c.real.ordTicket == 0 && CountOwnOrders(c.sym, 0) == 0)
         return changed;
      int left = CancelOwnOrders(c, 0, posNow ? "建玉あり" : "取消");
      if(left > 0 || c.real.ordTicket != 0)
         RetryLater(c, now);
      else
        {
         RetryReset(c);
         if(StringLen(c.real.cancelMsg) > 0 && c.real.chkTicket == 0)
           {
            c.nfHas = false;
            Notify(c.real.cancelMsg);
           }
         c.real.cancelMsg = "";
        }
      return true;
     }
   //--- 置きたい注文がある：追っていない自分の注文は先に取消す（二重の約定を防ぐ）
   if(CountOwnOrders(c.sym, c.real.ordTicket) > 0)
     {
      CancelOwnOrders(c, c.real.ordTicket, "引き継げない注文");
      RetryLater(c, now);
      return true;
     }
   SSetup w;
   w = c.real.wantSetup;
   if(c.real.ordTicket != 0 && c.real.ordDir == w.dir && c.real.ordKeyTime == w.key_time &&
      NormalizeDouble(w.price, c.digits) == c.real.ordPrice && NormalizeDouble(w.sl, c.digits) == c.real.ordSl)
     {
      c.real.ordSetup = w;
      return changed;                              // すでに置きたい注文どおり
     }
   int r = 0;
   if(c.real.ordTicket != 0)
     {
      if(c.real.ordDir == w.dir && c.real.ordKeyTime == w.key_time)
         r = RealModifyOrder(c, w);
      else
        {
         ulong old = c.real.ordTicket;
         int cr = CancelTicket(c, old, "別の key に置き換え");
         if(cr == FUS_CXL_FAIL)
            r = 0;
         else
            if(cr != FUS_CXL_DONE)
              {
               NoteVanished(c, old);              // 取消の前に約定（一部約定）していた：新しい注文は出さない
               c.real.ClearOrder();
               r = 1;
              }
            else
              {
               c.real.ClearOrder();
               r = RealPlaceOrder(c, w);
              }
        }
     }
   else
      r = RealPlaceOrder(c, w);
   if(r == 0)
      RetryLater(c, now);
   else
      RetryReset(c);
   if(r < 0)
      c.real.want = false;                         // この足は見送り（次の確定足で評価し直す）
   return true;
  }

//--- 起動・再接続・読み直しの後：口座にある自分の注文・建玉・約定履歴を読む
void RealAdopt(CSymbolCtx *c)
  {
   int n = c.eng.m_n;
   if(n <= 0)
      return;
   //--- 約定済み key（自分のマジックの約定履歴から。足番号は読み込んだ足で決まるので毎回作り直す）
   c.real.cons.Clear();
   if(HistorySelect(c.eng.m_T[0], NowServer() + 86400))
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
         int d = 0;
         datetime kt = 0;
         int ri = c.real.FindRec(ot);
         if(ri >= 0)
           {
            d = c.real.recDir[ri];
            kt = c.real.recKeyTime[ri];
           }
         else
           {
            string cmt = HistoryOrderGetString(ot, ORDER_COMMENT);
            if(StringLen(cmt) == 0)
               cmt = HistoryDealGetString(dt, DEAL_COMMENT);
            if(!ParseRealComment(cmt, d, kt))
               continue;
           }
         int ki = c.eng.IndexOfTime(kt);
         if(ki >= 0)
            c.real.cons.Add(d, ki);
        }
     }
   //--- 追っている建玉・確かめ中の約定の key も入れる
   if(c.real.posTicket != 0 && c.real.posKeyTime > 0)
     {
      int k1 = c.eng.IndexOfTime(c.real.posKeyTime);
      if(k1 >= 0)
         c.real.cons.Add(c.real.posDir, k1);
     }
   if(c.real.fillPosId != 0 && c.real.fillDir != 0 && c.real.fillKeyTime > 0)
     {
      int k2 = c.eng.IndexOfTime(c.real.fillKeyTime);
      if(k2 >= 0)
         c.real.cons.Add(c.real.fillDir, k2);
     }
   //--- 待機注文：コメント（または記録）から key を読める最初の逆指値を引き継ぐ。ほかは RealApply が取消す。
   //    追っていた注文が切断中に消えていたら、約定（してすぐ閉じた場合も）かどうかを履歴で確かめる
   if(c.real.ordTicket != 0 && c.real.chkTicket == 0 && !OrderSelect(c.real.ordTicket))
      NoteVanished(c, c.real.ordTicket);
   SSetup keep;
   keep = c.real.ordSetup;                         // 自分が置いた注文を引き継ぎ直すときは、判定の値（ATR・スコア・TP1 など）を残す
   ulong keepT = c.real.ordTicket;
   c.real.ClearOrder();
   for(int j = OrdersTotal() - 1; j >= 0; j--)
     {
      ulong ot2 = OrderGetTicket(j);
      if(ot2 == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != c.sym || OrderGetInteger(ORDER_MAGIC) != InpMagicNumber)
         continue;
      long otype = OrderGetInteger(ORDER_TYPE);
      int d2 = 0;
      datetime kt2 = 0;
      bool okc = ParseRealComment(OrderGetString(ORDER_COMMENT), d2, kt2);
      int ri2 = c.real.FindRec(ot2);
      if(ri2 >= 0)
        {
         d2 = c.real.recDir[ri2];
         kt2 = c.real.recKeyTime[ri2];
         okc = true;
        }
      bool isStop = ((otype == ORDER_TYPE_BUY_STOP && d2 == 1) || (otype == ORDER_TYPE_SELL_STOP && d2 == -1));
      int ki2 = okc ? c.eng.IndexOfTime(kt2) : -1;
      if(c.real.ordTicket != 0 || !isStop || ki2 < 0)
        {
         PrintFormat("[FUSION] %s 引き継げない注文 #%I64u は取消します", c.sym, ot2);
         continue;
        }
      c.real.ordTicket = ot2;
      c.real.ordDir = d2;
      c.real.ordKeyTime = kt2;
      c.real.ordPrice = OrderGetDouble(ORDER_PRICE_OPEN);
      c.real.ordSl = OrderGetDouble(ORDER_SL);
      if(ot2 == keepT && keep.dir == d2 && keep.key_time == kt2)
         c.real.ordSetup = keep;
      c.real.ordSetup.dir = d2;
      c.real.ordSetup.key_idx = ki2;                // 足番号は読み直しで変わりうる
      c.real.ordSetup.key_time = kt2;
      c.real.ordSetup.price = c.real.ordPrice;
      c.real.ordSetup.sl = c.real.ordSl;
      if(ri2 < 0)
         c.real.Remember(ot2, d2, kt2, c.real.ordPrice, 0);
     }
   //--- 建玉：追っていた建玉なら足番号だけ計算し直す。追っていなければ引き継ぐ（記録にない建玉は通知しない）
   ulong tk = 0;
   bool has = FindPosition(c.sym, tk);
   if(has && c.real.posTicket != 0 && tk != c.real.posTicket && PositionSelectByTicket(c.real.posTicket))
      tk = c.real.posTicket;                       // 2本あるときは、追っている建玉を追い続ける
   if(has && PositionSelectByTicket(tk))
     {
      if(c.real.posTicket == tk)
        {
         c.real.posEntryIdx = c.eng.IndexOfBarContaining(c.real.posTime);
         c.real.posSl = PositionGetDouble(POSITION_SL);
        }
      else
         if(c.real.posTicket == 0)
            TrackNewPosition(c, tk);
     }
   //--- 停止・切断の間に、建玉の決済足や休場明けを過ぎていないか（RealService がこの後すぐ確かめる）
   c.real.missCheck = true;
   CleanIslGvs(c);
   //--- 口座に残っていた逆指値は「通知済み」とする（新しく置く注文は通知する）
   c.nfHas = (c.real.ordTicket != 0);
   c.nfDir = c.real.ordDir;
   c.nfKeyTime = c.real.ordKeyTime;
   c.nfPrice = c.real.ordPrice;
   c.nfSl = c.real.ordSl;
   g_panelDirty = true;
  }

//--- 使われなくなった初期 SL のグローバル変数を消す（この銘柄の、閉じたことを約定履歴で確かめた建玉のもの。
//    口座の同期が終わっていないと建玉が見えないことがあるので、見えないだけでは消さない。履歴でも確かめられないものは
//    FUS_ISL_KEEP_DAYS 日より古くなってから消す）
void CleanIslGvs(CSymbolCtx *c)
  {
   string prefix = GvBase(c) + "_I";
   int plen = StringLen(prefix);
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
     {
      string nm = GlobalVariableName(i);
      if(StringFind(nm, prefix) != 0)
         continue;
      long pid = StringToInteger(StringSubstr(nm, plen));
      if(pid <= 0 || pid == c.real.posId || PositionIdOpen(pid))
         continue;
      bool old = ((long)TimeLocal() - (long)GlobalVariableTime(nm) > (long)FUS_ISL_KEEP_DAYS * 86400);
      if(old || PositionClosedInHistory(pid))
         GlobalVariableDel(nm);
     }
  }

//--- 接続して口座の同期を待った後に1回：この EA（この回の設定）が管理していない FUSION の注文・建玉（コメントが FC で
//    始まる）を数えて知らせる。監視銘柄・マジックを変えた、自動売買を OFF にした、などでトレール・週末決済・休場明けの
//    決済から外れたもの。別のチャートの FX_Fusion_EA（そのマジック）が監視の権利を持つ銘柄のものは、そちらが管理するとみなす
void WarnForeignOrders(void)
  {
   int nOrd = 0, nPos = 0;
   string syms = "";
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t == 0)
         continue;
      string so = OrderGetString(ORDER_SYMBOL);
      if(UnmanagedFusion(so, OrderGetInteger(ORDER_MAGIC), OrderGetString(ORDER_COMMENT)))
        {
         nOrd++;
         AddSymbolName(syms, so);
        }
     }
   for(int j = PositionsTotal() - 1; j >= 0; j--)
     {
      ulong p = PositionGetTicket(j);
      if(p == 0)
         continue;
      string sp = PositionGetString(POSITION_SYMBOL);
      if(UnmanagedFusion(sp, PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_COMMENT)))
        {
         nPos++;
         AddSymbolName(syms, sp);
        }
     }
   if(nOrd + nPos > 0)
      Notify(StringFormat("%s 注意: この EA が管理していない FUSION の注文 %d 件・建玉 %d 件があります（%s）。銘柄・マジック・自動売買の設定を変えた？ トレール・週末決済の対象外なので、手動で整理してください",
                          ModeTag(), nOrd, nPos, syms), 1);
  }

//--- FUSION の注文・建玉を、この EA も、別のチャートの FX_Fusion_EA も管理していないか
bool UnmanagedFusion(const string sym, const long magic, const string cmt)
  {
   int d = 0;
   datetime kt = 0;
   if(!ParseRealComment(cmt, d, kt))
      return false;                                 // FUSION の注文・建玉ではない
   if(InpAutoTrade && magic == InpMagicNumber && IsLockedHere(sym))
      return false;                                 // この EA が管理している
   string ln = LockNameOf(magic, sym);
   if(GlobalVariableCheck(ln))
     {
      double owner = GlobalVariableGet(ln);
      if(owner != 0.0 && owner != g_token)
         return false;                              // 別のチャートの EA が監視中
     }
   return true;
  }

//--- この EA が監視の権利を持っている銘柄か
bool IsLockedHere(const string sym)
  {
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(c.sym == sym && c.locked)
         return true;
     }
   return false;
  }

//--- カンマ区切りの銘柄名の一覧に足す（重複は足さない）
void AddSymbolName(string &list, const string sym)
  {
   if(StringFind("," + list + ",", "," + sym + ",") >= 0)
      return;
   list += (StringLen(list) > 0 ? "," : "") + sym;
  }

//--- 停止時：自分の注文・建玉が残っていれば、管理されなくなることを知らせる
void WarnLeftovers(const int reason)
  {
   if(reason == REASON_CHARTCHANGE || reason == REASON_PARAMETERS || reason == REASON_RECOMPILE)
      return;                                           // すぐ再初期化して引き継ぐ
   int nOrd = 0, nPos = 0;
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(!c.locked)
         continue;
      nOrd += CountOwnOrders(c.sym, 0);
      if(HasOwnPosition(c.sym))
         nPos++;
     }
   if(nOrd == 0 && nPos == 0)
      return;
   string msg = StringFormat("[FUSION自動] 注意: EA が止まりました（理由 %d）。自分の待機注文 %d 件・建玉 %d 件が残っていて、管理されません（トレール・週末決済なし）。必要なら手動で整理してください",
                             reason, nOrd, nPos);
   Print(msg);
   LogNotify(msg);
   if(InpPushNotify && TerminalInfoInteger(TERMINAL_NOTIFICATIONS_ENABLED) != 0 && !SendNotification(StringSubstr(msg, 0, 255)))
      Print("[FUSION] 停止の通知を送れませんでした");
  }

//+------------------------------------------------------------------+
//| 時差の点検（InpServerOffsetHours。1日1回）                          |
//|  サーバーの GMT オフセット（TimeTradeServer−TimeGMT）と米国の夏時間 |
//|  から期待値を出し、入力と違えばパネルと通知で知らせる（判定は変えない）|
//+------------------------------------------------------------------+
bool UsDst(const datetime gmt)
  {
   MqlDateTime s;
   TimeToStruct(gmt, s);
   int y = s.year;
   //--- 3月第2日曜 2:00 EST（07:00 UTC）〜 11月第1日曜 2:00 EDT（06:00 UTC）
   int w1 = FE_DayOfWeek(FE_MakeDate(y, 3, 1));
   int sun1 = 1 + (7 - w1) % 7;
   datetime start = (datetime)((long)FE_MakeDate(y, 3, sun1 + 7) + 7 * 3600);
   int w2 = FE_DayOfWeek(FE_MakeDate(y, 11, 1));
   int sun2 = 1 + (7 - w2) % 7;
   datetime end = (datetime)((long)FE_MakeDate(y, 11, sun2) + 6 * 3600);
   return (gmt >= start && gmt < end);
  }

void CheckServerOffset(void)
  {
   if(g_tester || !g_conn)
      return;
   datetime srv = TimeTradeServer();
   datetime gmt = TimeGMT();
   datetime tc = TimeCurrent();
   if(srv <= 0 || gmt <= 0 || tc <= 0)
      return;
   //--- 新しい気配が届いているとき（最後の気配の時刻がいまのサーバー時間に近い）だけ点検する。接続の前や週末は
   //    TimeTradeServer が古い時差で計算されていることがあり、誤って知らせないため（つながり直すたびに点検し直す）
   long lag = (long)srv - (long)tc;
   if(lag > 600 || lag < -600)
      return;
   int day = (int)((long)srv / 86400);
   if(day == g_offsetDay)
      return;
   g_offsetDay = day;
   int srvOff = (int)MathRound((double)((long)srv - (long)gmt) / 3600.0);
   int ny = UsDst(gmt) ? -4 : -5;
   int expect = srvOff - (ny + 7);
   bool bad = (expect != InpServerOffsetHours);
   if(bad)
      g_offsetNote = StringFormat("時差の確認: サーバー GMT%+d・NY GMT%+d → InpServerOffsetHours は %d のはず（いまは %d）",
                                  srvOff, ny, expect, InpServerOffsetHours);
   else
      g_offsetNote = "";
   if(bad && !g_offsetBad)
      Notify(StringFormat("%s 注意: %s。時刻ルール（新規停止・週末決済）が1時間ずれます。PC の時計とタイムゾーンも確かめてください（TimeGMT は PC の時計から計算）",
                          ModeTag(), g_offsetNote), 1);
   if(!bad && g_offsetBad)
      PrintFormat("[FUSION] 時差は InpServerOffsetHours=%d と合っています", InpServerOffsetHours);
   g_offsetBad = bad;
   g_panelDirty = true;
  }

//+------------------------------------------------------------------+
//| パネル（SPEC §16.3）                                              |
//|  行を組み立ててから描く。背景は行より先に作る（同じ前景の物体は、  |
//|  あとから作ったものが上に描かれる。名前も "0BG" で行のラベル "P0"… |
//|  より前に並ぶ）。                                                  |
//+------------------------------------------------------------------+
void PanelAdd(const string text, const color clr)
  {
   ArrayResize(g_plText, g_plN + 1, 64);
   ArrayResize(g_plClr, g_plN + 1, 64);
   g_plText[g_plN] = text;
   g_plClr[g_plN] = clr;
   g_plN++;
  }

//--- 長い行は空白の位置で折り返す（続きの行は4文字下げる。どの行もラベルの上限 63 文字に収める）
void PanelText(const string text, const color clr)
  {
   string rest = text;
   bool first = true;
   while(StringLen(rest) > 0)
     {
      int lim = first ? FUS_WRAP : FUS_WRAP - 4;
      string piece = rest;
      if(StringLen(rest) > lim)
        {
         int cut = lim;
         for(int i = lim; i > 20; i--)
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
      PanelAdd(first ? piece : "    " + piece, clr);
      first = false;
     }
  }

//--- 背景（新しく作ったら true）
bool PanelBackground(const int x, const int y, const int w, const int h)
  {
   string name = g_prefix + "0BG";
   bool made = false;
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
      made = true;
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   return made;
  }

//--- 行のラベル（まだ作っていない行だけ作る。毎回 ObjectFind で待たない）
void PanelLine(const int i, const int x, const int y, const string text, const color clr)
  {
   string name = g_prefix + "P" + IntegerToString(i);
   if(i >= g_panelLines)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
     }
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y + i * g_lineH);
   ObjectSetString(0, name, OBJPROP_FONT, InpPanelFont);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpPanelFontSize);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

//--- 組み立てた行を描く（チャートの高さに収まらない分は「…ほか N 行」にまとめる）
void PanelRender(void)
  {
   int x = InpPanelX;
   int y = InpPanelY;
   if(ChartGetInteger(0, CHART_SHOW_ONE_CLICK) != 0)
      y += FUS_ONECLICK_H;                              // ワンクリック取引パネル（左上）を避ける
   int chartH = (int)ChartGetInteger(0, CHART_HEIGHT_IN_PIXELS, 0);
   int maxLines = (chartH > 0) ? (chartH - y - 12) / g_lineH : g_plN;
   if(maxLines < 4)
      maxLines = 4;
   int show = g_plN;
   bool cut = false;
   if(show > maxLines)
     {
      show = maxLines - 1;
      cut = true;
     }
   int lines = show + (cut ? 1 : 0);
   //--- 幅は一番長い行に合わせる（全角の幅はフォントで違う）
   int width = FUS_PANEL_MINW;
   if(TextSetFont(InpPanelFont, -10 * InpPanelFontSize, 0))
      for(int i = 0; i < show; i++)
        {
         uint tw = 0, th = 0;
         if(TextGetSize(g_plText[i], tw, th) && (int)tw + 16 > width)
            width = (int)tw + 16;
        }
   if(PanelBackground(x - 6, y - 4, width, lines * g_lineH + 8))
     {
      //--- 背景を作り直した（消されていた）：行も作り直して背景の上に出す
      for(int d = 0; d < g_panelLines; d++)
         ObjectDelete(0, g_prefix + "P" + IntegerToString(d));
      g_panelLines = 0;
     }
   for(int k = 0; k < show; k++)
      PanelLine(k, x, y, g_plText[k], g_plClr[k]);
   if(cut)
      PanelLine(show, x, y, StringFormat("…ほか %d 行（表示しきれない分）", g_plN - show), clrGray);
   for(int e = lines; e < g_panelLines; e++)
      ObjectDelete(0, g_prefix + "P" + IntegerToString(e));
   g_panelLines = lines;
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

//--- 自動売買の注意（取引できない・決済に失敗し続けている・市場が閉まっていて決済を待っている）
void RealPanelLines(CSymbolCtx *c)
  {
   if(StringLen(c.real.tradeNote) > 0)
      PanelText("  自動売買できない: " + c.real.tradeNote, clrRed);
   if(c.real.closeReq != 0 && c.real.holdMs != 0)
      PanelText(StringFormat("  市場が閉まっているため、取引が再開したら決済する（%s）", FE_ReasonName(c.real.closeReq)), clrOrange);
   else
      if(c.real.closeReq != 0 && c.real.closeFails > 0)
         PanelText(StringFormat("  決済を再試行中（%s。失敗 %d 回）", FE_ReasonName(c.real.closeReq), c.real.closeFails), clrRed);
  }

void UpdatePanel(void)
  {
   g_plN = 0;
   PanelText("FUSION-CORE v1.0（H1 単一時間足） " + (InpAutoTrade ? "自動売買ON" : "シグナル通知のみ") + " " + ConfigName(), clrGold);
   if(!g_tester && !g_conn)
      PanelText("取引サーバーに未接続（つながると足の処理と自動売買を再開する）", clrTomato);
   if(InpAutoTrade && StringLen(g_tradeNote) > 0)
      PanelText("自動売買できない（全銘柄）: " + g_tradeNote, clrRed);
   if(StringLen(g_offsetNote) > 0)
      PanelText(g_offsetNote, clrTomato);
   for(int i = 0; i < g_nctx; i++)
     {
      CSymbolCtx *c = g_ctx[i];
      if(!c.locked)
        {
         PanelText(c.sym + "  別のチャートの EA が監視中（ここでは監視しない）", clrGray);
         continue;
        }
      if(!c.ready)
        {
         PanelText(c.sym + "  準備中（" + c.note + "）", clrGray);
         if(InpAutoTrade)
            RealPanelLines(c);
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
      PanelText(StringFormat("%s %s %s 日/4H/1H:%s/%s/%s END%d%s %s", c.sym, st, G1Text(c), Sgn(td), Sgn(tb), Sgn(ts),
                             c.eng.DowE(c.eng.m_db, t), war, c.note), sc);
      if(StringLen(c.alert) > 0)
         PanelText("  " + c.alert, clrRed);
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
      PanelText(vals, clrWhite);
      //--- 3行目：直近の理由コード・エリア
      string why = "  直近 買:" + FE_CodeName(c.eng.m_lastBuy.code) + " 売:" + FE_CodeName(c.eng.m_lastSell.code);
      if(c.eng.m_lastTcode != RC_NONE)
         why += " 見送り:" + FE_CodeName(c.eng.m_lastTcode) + "(" + FE_CodeDesc(c.eng.m_lastTcode) + ")";
      PanelText(why + " " + AreaText(c), clrSilver);
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
      PanelText(od, clrLightCyan);
      if(InpAutoTrade)
         RealPanelLines(c);
      //--- 5行目：最後に処理した確定足・累計・次の暦イベント
      int nt = 0, w = 0, cl = 0, ml = 0;
      double sr = 0.0;
      c.eng.Stats(nt, w, sr, cl, ml);
      string stat = "  確定足" + TimeToString(c.lastDone, TIME_DATE | TIME_MINUTES) +
                    StringFormat(" 仮想累計 %d回 勝率%.0f%% 総R%+.1f 連敗%d(最大%d)", nt, (nt > 0) ? 100.0 * w / nt : 0.0, sr, cl, ml);
      if(InpAutoTrade)
         stat += StringFormat(" | 実 %d回 %+.1fR", c.real.nTrades, c.real.sumR);
      datetime nf = 0;
      if(c.eng.m_n > 0)
         nf = c.eng.NextFlatClose((datetime)((long)c.eng.m_T[c.eng.m_n - 1] + 3600));
      if(nf > 0)
         stat += " 次の全決済 " + TimeToString(nf, TIME_DATE | TIME_MINUTES);
      PanelText(stat, clrSilver);
     }
   //--- 固定文言（SPEC §16.3。最終検証の後の文言は付録E の E-20）
   PanelAdd("勝率は25〜30%前後、損益の中央値は−1R、利益は週末まで持った少数の取引に集中、", clrTomato);
   PanelAdd("10〜20連敗は想定内。優位性は未確認（最終検証は不合格）。", clrTomato);
   PanelAdd("裁量で分割・建値・早利確を加えると別の戦略になる", clrTomato);
   PanelRender();
   g_panelDirty = false;
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| チャート描画（チャートの銘柄だけ）                                 |
//|  毎回 ObjectsDeleteAll で消してから作り直すので、存在は確かめない    |
//|  （ObjectFind はチャートの処理を待つ同期関数で、数百回呼ぶと重い）。 |
//|  どれも背景（OBJPROP_BACK）に置き、パネルの上に重ならないようにする。|
//+------------------------------------------------------------------+
void DrawHLine(const string name, const double price, const color clr, const int width, const ENUM_LINE_STYLE style, const string text)
  {
   ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
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
   ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
  }

void DrawArrow(const string name, const datetime t, const double price, const int code, const ENUM_ARROW_ANCHOR anchor, const color clr)
  {
   ObjectCreate(0, name, OBJ_ARROW, 0, t, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, anchor);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
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
   int from = (int)MathMax(1, n - 240);
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
      DrawArrow(pf + "SH_" + IntegerToString(j), c.eng.m_T[j], c.eng.m_H[j], 234, ANCHOR_BOTTOM, clrTomato);
     }
   for(int p2 = 0; p2 < c.eng.m_bb.m_nl; p2++)
     {
      int j2 = c.eng.m_bb.m_lo[p2];
      if(j2 < lo)
         continue;
      DrawArrow(pf + "SL_" + IntegerToString(j2), c.eng.m_T[j2], c.eng.m_L[j2], 233, ANCHOR_TOP, clrDeepSkyBlue);
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
                   (int)MathMin(5, MathMax(1, tch)), (tch <= 1) ? STYLE_DOT : STYLE_SOLID,
                   StringFormat("節目 touch=%d 高%d安%d%s", tch, c.eng.m_lv[bi].nh, c.eng.m_lv[bi].nl, c.eng.m_lv[bi].d1 ? " 日足級" : ""));
        }
     }
   //--- 逆指値・SL・TP1/TP2 の目安線、建玉（仮想ブローカー）
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
