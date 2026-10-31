//+------------------------------------------------------------------+
//|  FX4Pattern_EA.mq5                                               |
//|  4つの鉄板エントリーパターン ― パターン① 自動売買EA             |
//|  戦略: 4時間足レベルの押し目・戻り目                             |
//|                                                                  |
//|  【手法の概要】                                                   |
//|  ・4時間足のトレンド方向に対して、1時間足が一時的に逆行した後    |
//|    再び4時間足方向へ転換した瞬間をエントリーポイントとする         |
//|  ・日足フィルターで大きな流れと逆方向のトレードを回避            |
//|                                                                  |
//|  【推奨チャート】                                                 |
//|  ・USDJPY / EURUSD / GBPUSD / XAUUSD（ゴールド）他               |
//|  ・動作時間足: H1（1時間足）                                      |
//|                                                                  |
//|  【MA設定（マニュアル準拠）】                                     |
//|  ・1H MA20  = 1時間足の短期MA（青）                              |
//|  ・1H MA80  = 4時間足の20SMA相当（赤）                           |
//|  ・1H MA480 = 日足の20SMA相当（黄）                              |
//+------------------------------------------------------------------+
#property copyright "FX 4Pattern Strategy"
#property version   "1.10"
#property description "4つの鉄板パターン① ― 4時間足レベルの押し目・戻り目"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//+------------------------------------------------------------------+
//| 入力パラメータ                                                    |
//+------------------------------------------------------------------+
input group "=== リスク管理 ==="
input double InpRiskPercent   = 1.0;   // 1トレードのリスク率 (口座残高の%)
input double InpRiskReward    = 2.0;   // リスクリワード比 (SL:TP = 1:この値)
input double InpSL_ATR_Mult   = 2.0;  // SL幅 = ATR(14) × この値
input int    InpMaxPositions  = 1;     // 最大同時保有ポジション数

input group "=== 移動平均線（1時間足チャートに表示する値）==="
input int    InpMA_1H         = 20;   // 1時間足MA（青線）
input int    InpMA_4H_Equiv   = 80;   // 4時間足MA相当（赤線: 1H×4）
input int    InpMA_Day_Equiv  = 480;  // 日足MA相当（黄線: 1H×24）

input group "=== トレンド判定 ==="
input int    InpSlopeWindow   = 5;    // MAスロープ判定ウィンドウ（本数）
input bool   InpUseDailyFilter = true; // 日足フィルター（日足と4H方向不一致時はスキップ）
input bool   InpAllowBuy      = true;  // 買いトレードを許可
input bool   InpAllowSell     = true;  // 売りトレードを許可

input group "=== 時間フィルター ==="
input int    InpStartHour     = 2;    // 取引開始時間 (サーバー時刻)
input int    InpEndHour       = 22;   // 取引終了時間 (サーバー時刻)
input bool   InpNoFridayNight = true; // 金曜22時以降はポジション不可

input group "=== その他 ==="
input int    InpMagicNumber   = 20240001; // マジックナンバー

//+------------------------------------------------------------------+
//| グローバル変数                                                    |
//+------------------------------------------------------------------+
CTrade        Trade;
CPositionInfo PositionInfo;

int hMA_1H, hMA_4H, hMA_Day, hATR;
datetime      g_lastBarTime = 0;

//+------------------------------------------------------------------+
//| 初期化                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   // 1時間足チャート上に3本のMAとATRを作成
   hMA_1H  = iMA(_Symbol, PERIOD_H1, InpMA_1H,        0, MODE_SMA, PRICE_CLOSE);
   hMA_4H  = iMA(_Symbol, PERIOD_H1, InpMA_4H_Equiv,  0, MODE_SMA, PRICE_CLOSE);
   hMA_Day = iMA(_Symbol, PERIOD_H1, InpMA_Day_Equiv, 0, MODE_SMA, PRICE_CLOSE);
   hATR    = iATR(_Symbol, PERIOD_H1, 14);

   if(hMA_1H == INVALID_HANDLE || hMA_4H == INVALID_HANDLE ||
      hMA_Day == INVALID_HANDLE || hATR == INVALID_HANDLE)
   {
      Alert("FX4Pattern_EA: インジケーター初期化失敗");
      return INIT_FAILED;
   }

   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);

   PrintFormat("=== FX4Pattern_EA 起動 ===");
   PrintFormat("通貨ペア: %s | リスク: %.1f%% | RR: 1:%.1f | SL: ATR×%.1f",
               _Symbol, InpRiskPercent, InpRiskReward, InpSL_ATR_Mult);
   PrintFormat("MA設定: 1H=%d, 4H相当=%d, 日足相当=%d",
               InpMA_1H, InpMA_4H_Equiv, InpMA_Day_Equiv);
   PrintFormat("日足フィルター: %s", InpUseDailyFilter ? "有効" : "無効");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| 終了処理                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(hMA_1H);
   IndicatorRelease(hMA_4H);
   IndicatorRelease(hMA_Day);
   IndicatorRelease(hATR);
}

//+------------------------------------------------------------------+
//| メインループ                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1時間足の新バー確定時のみ処理（リペイント防止）
   datetime barTime = iTime(_Symbol, PERIOD_H1, 0);
   if(barTime == g_lastBarTime) return;
   g_lastBarTime = barTime;

   // 時間フィルター
   if(!IsTradeTime()) return;

   // 既存ポジションの管理（必要に応じて追加可能）
   if(CountPositions() >= InpMaxPositions) return;

   // シグナル取得
   int signal = GetSignal();
   if(signal == 0) return;

   // エントリー実行
   if(signal ==  1 && InpAllowBuy)  OpenPosition(ORDER_TYPE_BUY);
   if(signal == -1 && InpAllowSell) OpenPosition(ORDER_TYPE_SELL);
}

//+------------------------------------------------------------------+
//| 取引時間チェック                                                  |
//+------------------------------------------------------------------+
bool IsTradeTime()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   // 土日はトレードしない
   if(dt.day_of_week == 0 || dt.day_of_week == 6) return false;

   // 金曜夜はポジション取らない
   if(InpNoFridayNight && dt.day_of_week == 5 && dt.hour >= 21) return false;

   // 時間帯フィルター
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;

   return true;
}

//+------------------------------------------------------------------+
//| このEAが持つポジション数を返す                                   |
//+------------------------------------------------------------------+
int CountPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionInfo.SelectByIndex(i))
         if(PositionInfo.Symbol() == _Symbol && PositionInfo.Magic() == InpMagicNumber)
            count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| MAのスロープ方向を返す                                           |
//|   +1 = 上昇傾向, -1 = 下降傾向, 0 = 判定不能                    |
//+------------------------------------------------------------------+
int GetMATrend(int handle, int shift)
{
   double now[], past[];
   ArraySetAsSeries(now,  true);
   ArraySetAsSeries(past, true);

   if(CopyBuffer(handle, 0, shift,                    1, now)  < 1) return 0;
   if(CopyBuffer(handle, 0, shift + InpSlopeWindow,   1, past) < 1) return 0;

   double diff = now[0] - past[0];
   double threshold = now[0] * 0.000005; // 有意なスロープかどうかの閾値

   if(diff >  threshold) return  1;
   if(diff < -threshold) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| エントリーシグナル取得                                           |
//|                                                                  |
//| パターン①: 4時間足レベルの押し目・戻り目                        |
//|                                                                  |
//| 買いシグナル:                                                    |
//|   ・4H MA (MA80) が上向き  → 4時間足は上昇トレンド              |
//|   ・1H MA (MA20) が前足で下向き → 一時的な押し目を形成中         |
//|   ・1H MA (MA20) が現在上向きに転換 → 押し目終了・再上昇         |
//|   ・（日足フィルターON時）日足MA (MA480) も上向き               |
//|                                                                  |
//| 売りシグナル: 上記の逆                                           |
//+------------------------------------------------------------------+
int GetSignal()
{
   // バー[1]（直前確定バー）基準で判定（リペイント防止）
   int trend_4H_cur  = GetMATrend(hMA_4H,  1);      // 4H MAの現在トレンド
   int trend_1H_cur  = GetMATrend(hMA_1H,  1);      // 1H MAの現在トレンド
   int trend_1H_prev = GetMATrend(hMA_1H,  1 + InpSlopeWindow); // 1H MAの前トレンド
   int trend_Day_cur = GetMATrend(hMA_Day, 1);      // 日足MAの現在トレンド

   // --- 日足フィルター ---
   // 日足と4H方向が真逆（戦争状態）ならトレードしない
   if(InpUseDailyFilter)
   {
      if(trend_Day_cur == -1 && trend_4H_cur == 1)  return 0; // 日足下降 vs 4H上昇
      if(trend_Day_cur ==  1 && trend_4H_cur == -1) return 0; // 日足上昇 vs 4H下降
   }

   // --- 買いシグナル ---
   // 4H上昇 & 1HMAが下向き→上向きに転換
   if(trend_4H_cur == 1 && trend_1H_cur == 1 && trend_1H_prev == -1)
      return 1;

   // --- 売りシグナル ---
   // 4H下降 & 1HMAが上向き→下向きに転換
   if(trend_4H_cur == -1 && trend_1H_cur == -1 && trend_1H_prev == 1)
      return -1;

   return 0;
}

//+------------------------------------------------------------------+
//| ポジションオープン                                               |
//+------------------------------------------------------------------+
void OpenPosition(ENUM_ORDER_TYPE type)
{
   // ATR取得
   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(hATR, 0, 1, 1, atr) < 1)
   {
      Print("ATR取得失敗");
      return;
   }
   double atrVal = atr[0];
   if(atrVal <= 0) return;

   // エントリー価格・SL・TP計算
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   double entryPrice = (type == ORDER_TYPE_BUY) ? ask : bid;
   double slDist     = atrVal * InpSL_ATR_Mult;
   double tpDist     = slDist * InpRiskReward;

   double sl = (type == ORDER_TYPE_BUY) ? entryPrice - slDist : entryPrice + slDist;
   double tp = (type == ORDER_TYPE_BUY) ? entryPrice + tpDist : entryPrice - tpDist;

   // 正規化
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);

   // ロットサイズ計算
   double lots = CalcLotSize(slDist);
   if(lots <= 0) return;

   // ログ
   string dir = (type == ORDER_TYPE_BUY) ? "BUY" : "SELL";
   PrintFormat("[シグナル] %s %s | Entry=%.5f | SL=%.5f(%.1fpips) | TP=%.5f | ATR=%.5f | Lots=%.2f",
               _Symbol, dir, entryPrice,
               sl, slDist / SymbolInfoDouble(_Symbol, SYMBOL_POINT) / 10,
               tp, atrVal, lots);

   // 注文送信
   string comment = StringFormat("4P1_%s_RR%.1f", dir, InpRiskReward);
   bool ok = (type == ORDER_TYPE_BUY)
      ? Trade.Buy(lots,  _Symbol, 0, sl, tp, comment)
      : Trade.Sell(lots, _Symbol, 0, sl, tp, comment);

   if(!ok)
      PrintFormat("注文失敗 [%d]: %s", GetLastError(), Trade.ResultComment());
}

//+------------------------------------------------------------------+
//| ロットサイズ計算                                                 |
//| リスク額 = 口座残高 × リスク率%                                 |
//| ロット = リスク額 ÷ (SL幅 × 1ロットあたりのティック価値)        |
//+------------------------------------------------------------------+
double CalcLotSize(double slDistPrice)
{
   double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney  = balance * InpRiskPercent / 100.0;

   double tickSize   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double minLot     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot     = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(tickSize <= 0 || tickValue <= 0) return minLot;

   double slTicks         = slDistPrice / tickSize;
   double slValuePerLot   = slTicks * tickValue;
   if(slValuePerLot <= 0) return minLot;

   double lots = MathFloor((riskMoney / slValuePerLot) / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));

   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| ストラテジーテスター用レポート（オプション）                     |
//+------------------------------------------------------------------+
double OnTester()
{
   // カスタム最適化指標: プロフィットファクター × 勝率
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double wr = TesterStatistics(STAT_TRADES) > 0
             ? TesterStatistics(STAT_PROFIT_TRADES) / TesterStatistics(STAT_TRADES)
             : 0;
   return pf * wr * 100;
}
//+------------------------------------------------------------------+
