//+------------------------------------------------------------------+
//|  FX4Pattern_Dashboard.mq5                                        |
//|  4P-Score リアルタイムチャートダッシュボード                     |
//|                                                                  |
//|  H1チャートにアタッチするだけで、日足〜15分足のダウ理論トレンド  |
//|  状態・シグナルスコア・損益履歴をチャート上に表示する            |
//+------------------------------------------------------------------+
#property copyright "FX 4Pattern Dashboard"
#property version   "1.00"
#property description "4P-Score リアルタイムダッシュボード（チャートオーバーレイ）"

#include <Trade\PositionInfo.mqh>
#include <Trade\DealInfo.mqh>

//+------------------------------------------------------------------+
//| 入力パラメータ                                                    |
//+------------------------------------------------------------------+
input group "=== 表示設定 ==="
input int    InpPanelX       = 10;    // パネル左端 X位置（ピクセル）
input int    InpPanelY       = 30;    // パネル上端 Y位置（ピクセル）
input int    InpFontSize     = 9;     // フォントサイズ
input color  InpColorBull    = C'0,200,100';  // 上昇トレンド色（緑）
input color  InpColorBear    = C'220,60,60';  // 下降トレンド色（赤）
input color  InpColorRange   = C'160,160,160'; // レンジ色（グレー）
input color  InpColorBg      = C'13,17,23';   // 背景色
input color  InpColorBorder  = C'48,54,61';   // 枠線色
input color  InpColorText    = C'230,237,243'; // テキスト色
input color  InpColorTitle   = C'88,166,255';  // タイトル色

input group "=== スイング判定 ==="
input int    InpSwingDepth   = 3;     // スイング高値・安値の判定深さ
input int    InpLookback     = 300;   // 探索バー数

input group "=== 損益トラッキング ==="
input int    InpMagicNumber  = 20260002; // このダッシュボードと連動するEAのマジックナンバー
input int    InpHistoryDays  = 90;    // 損益履歴の参照期間（日数）

//+------------------------------------------------------------------+
//| オブジェクト名プレフィックス                                     |
//+------------------------------------------------------------------+
#define PREFIX "4PD_"

//+------------------------------------------------------------------+
//| インジケーターハンドル                                           |
//+------------------------------------------------------------------+
int hMA_M15, hMA_H1, hMA_H4, hMA_D1;
int hATR_H1, hATR_H4;
datetime g_lastBar = 0;

CPositionInfo PositionInfo;
CDealInfo     DealInfo;

//+------------------------------------------------------------------+
//| 初期化                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   hMA_M15 = iMA(_Symbol, PERIOD_M15, 20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_H1  = iMA(_Symbol, PERIOD_H1,  20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_H4  = iMA(_Symbol, PERIOD_H4,  20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_D1  = iMA(_Symbol, PERIOD_D1,  20, 0, MODE_SMA, PRICE_CLOSE);
   hATR_H1 = iATR(_Symbol, PERIOD_H1, 14);
   hATR_H4 = iATR(_Symbol, PERIOD_H4, 14);

   if(hMA_M15 == INVALID_HANDLE || hMA_H1 == INVALID_HANDLE ||
      hMA_H4  == INVALID_HANDLE || hMA_D1 == INVALID_HANDLE ||
      hATR_H1 == INVALID_HANDLE || hATR_H4 == INVALID_HANDLE)
   {
      Alert("4P-Dashboard: インジケーター初期化失敗");
      return INIT_FAILED;
   }

   EventSetTimer(5); // 5秒ごとに更新
   ChartSetInteger(0, CHART_SHOW_GRID, false);
   Print("=== 4P-Score ダッシュボード 起動 ===");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   DeleteAllObjects();
}

void OnTick()  { }
void OnTimer() { Redraw(); }

void OnChartEvent(const int id, const long& lp, const double& dp, const string& sp)
{
   if(id == CHARTEVENT_CHART_CHANGE) Redraw();
}

//+------------------------------------------------------------------+
//| 全オブジェクト削除                                               |
//+------------------------------------------------------------------+
void DeleteAllObjects()
{
   int total = ObjectsTotal(0, -1, -1);
   for(int i = total - 1; i >= 0; i--)
   {
      string name = ObjectName(0, i, -1, -1);
      if(StringFind(name, PREFIX) == 0)
         ObjectDelete(0, name);
   }
}

//+------------------------------------------------------------------+
//| ダウ理論トレンド判定                                             |
//+------------------------------------------------------------------+
int DowTrend(ENUM_TIMEFRAMES tf)
{
   int bars = MathMin(InpLookback, iBars(_Symbol, tf) - InpSwingDepth - 1);
   int depth = InpSwingDepth;

   // スイング高値・安値を収集（新しい順）
   double sh[];  // swing highs
   double sl[];  // swing lows
   ArrayResize(sh, 0); ArrayResize(sl, 0);

   for(int i = depth + 1; i < bars; i++)
   {
      double h = iHigh(_Symbol, tf, i);
      bool isH = true;
      for(int k = 1; k <= depth && isH; k++)
      {
         if(h <= iHigh(_Symbol, tf, i - k)) isH = false;
         if(h <  iHigh(_Symbol, tf, i + k)) isH = false;
      }
      if(isH) { ArrayResize(sh, ArraySize(sh) + 1); sh[ArraySize(sh)-1] = h; }
      if(ArraySize(sh) >= 3) break;
   }
   for(int i = depth + 1; i < bars; i++)
   {
      double l = iLow(_Symbol, tf, i);
      bool isL = true;
      for(int k = 1; k <= depth && isL; k++)
      {
         if(l >= iLow(_Symbol, tf, i - k)) isL = false;
         if(l >  iLow(_Symbol, tf, i + k)) isL = false;
      }
      if(isL) { ArrayResize(sl, ArraySize(sl) + 1); sl[ArraySize(sl)-1] = l; }
      if(ArraySize(sl) >= 3) break;
   }

   if(ArraySize(sh) < 2 || ArraySize(sl) < 2) return 0;

   bool hh = sh[0] > sh[1];
   bool hl = sl[0] > sl[1];
   bool lh = sh[0] < sh[1];
   bool ll = sl[0] < sl[1];

   if(hh && hl) return  1;
   if(lh && ll) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| 反対勢力スコア（0〜20点）                                        |
//| 4H・日足スイングの中で、4Hトレンド方向の進行を妨げる             |
//| 最寄りレベルまでの距離をATR(H4)比で採点                          |
//+------------------------------------------------------------------+
int OppForceScore(int dir)
{
   if(dir == 0) return 0;

   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(hATR_H4, 0, 1, 1, atr) < 1 || atr[0] <= 0) return 0;
   double atrVal = atr[0];

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double nearest = 0;
   bool found = false;

   ENUM_TIMEFRAMES tfs[2] = {PERIOD_H4, PERIOD_D1};
   int depth = InpSwingDepth;

   for(int t = 0; t < 2; t++)
   {
      int bars = MathMin(InpLookback, iBars(_Symbol, tfs[t]) - depth - 1);
      for(int i = depth + 1; i < bars; i++)
      {
         if(dir == -1) // 売り目線 → 直下のサポート（スイング安値）
         {
            double l = iLow(_Symbol, tfs[t], i);
            bool isL = true;
            for(int k = 1; k <= depth && isL; k++)
            {
               if(l >= iLow(_Symbol, tfs[t], i - k)) isL = false;
               if(l >  iLow(_Symbol, tfs[t], i + k)) isL = false;
            }
            if(isL && l < price)
               if(!found || l > nearest) { nearest = l; found = true; }
         }
         else          // 買い目線 → 直上のレジスタンス（スイング高値）
         {
            double h = iHigh(_Symbol, tfs[t], i);
            bool isH = true;
            for(int k = 1; k <= depth && isH; k++)
            {
               if(h <= iHigh(_Symbol, tfs[t], i - k)) isH = false;
               if(h <  iHigh(_Symbol, tfs[t], i + k)) isH = false;
            }
            if(isH && h > price)
               if(!found || h < nearest) { nearest = h; found = true; }
         }
      }
   }

   if(!found) return 20; // 反対勢力なし＝視界良好

   double distATR = MathAbs(price - nearest) / atrVal;
   if(distATR >= 3.0) return 20;
   if(distATR >= 2.0) return 10;
   if(distATR >= 1.0) return 5;
   return 0; // 近すぎる → エントリー見送り推奨
}

//+------------------------------------------------------------------+
//| テキストラベル作成・更新                                         |
//+------------------------------------------------------------------+
void Label(string name, int x, int y, string text, color clr, int fontSize = -1)
{
   string fullName = PREFIX + name;
   if(ObjectFind(0, fullName) < 0)
   {
      ObjectCreate(0, fullName, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, fullName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, fullName, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      ObjectSetString(0, fullName, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, fullName, OBJPROP_BACK, false);
      ObjectSetInteger(0, fullName, OBJPROP_SELECTABLE, false);
   }
   ObjectSetInteger(0, fullName, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, fullName, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, fullName, OBJPROP_TEXT, text);
   ObjectSetInteger(0, fullName, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, fullName, OBJPROP_FONTSIZE, fontSize < 0 ? InpFontSize : fontSize);
}

//+------------------------------------------------------------------+
//| 矩形背景作成                                                     |
//+------------------------------------------------------------------+
void Rect(string name, int x1, int y1, int x2, int y2, color clrBg, color clrBorder)
{
   string fullName = PREFIX + name;
   if(ObjectFind(0, fullName) < 0)
      ObjectCreate(0, fullName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, fullName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, fullName, OBJPROP_XDISTANCE, x1);
   ObjectSetInteger(0, fullName, OBJPROP_YDISTANCE, y1);
   ObjectSetInteger(0, fullName, OBJPROP_XSIZE, x2 - x1);
   ObjectSetInteger(0, fullName, OBJPROP_YSIZE, y2 - y1);
   ObjectSetInteger(0, fullName, OBJPROP_BGCOLOR, clrBg);
   ObjectSetInteger(0, fullName, OBJPROP_BORDER_COLOR, clrBorder);
   ObjectSetInteger(0, fullName, OBJPROP_BACK, true);
   ObjectSetInteger(0, fullName, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| トレンドインジケーターバー描画                                   |
//+------------------------------------------------------------------+
void TrendBar(string name, int x, int y, int w, int h, int trend)
{
   string fullName = PREFIX + name;
   if(ObjectFind(0, fullName) < 0)
      ObjectCreate(0, fullName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   color clr = trend == 1 ? InpColorBull : trend == -1 ? InpColorBear : InpColorRange;
   ObjectSetInteger(0, fullName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, fullName, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, fullName, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, fullName, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, fullName, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, fullName, OBJPROP_BGCOLOR, clr);
   ObjectSetInteger(0, fullName, OBJPROP_BORDER_COLOR, clr);
   ObjectSetInteger(0, fullName, OBJPROP_BACK, true);
   ObjectSetInteger(0, fullName, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| 損益履歴取得（直近N日間のクローズドトレード）                    |
//+------------------------------------------------------------------+
double GetHistoryPnL(int &winCount, int &lossCount, double &maxDD)
{
   winCount = 0; lossCount = 0; maxDD = 0;
   double totalPnL = 0, equity = 0, peak = 0;

   datetime from = TimeCurrent() - (datetime)(InpHistoryDays * 86400);
   HistorySelect(from, TimeCurrent());

   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      if(!DealInfo.SelectByIndex(i)) continue;
      if(DealInfo.Symbol() != _Symbol) continue;
      if(InpMagicNumber > 0 && DealInfo.Magic() != InpMagicNumber) continue;
      if(DealInfo.Entry() != DEAL_ENTRY_OUT) continue;

      double profit = DealInfo.Profit() + DealInfo.Swap() + DealInfo.Commission();
      totalPnL += profit;
      equity += profit;
      if(equity > peak) peak = equity;
      double dd = equity - peak;
      if(dd < maxDD) maxDD = dd;

      if(profit > 0) winCount++;
      else if(profit < 0) lossCount++;
   }
   return totalPnL;
}

//+------------------------------------------------------------------+
//| スコアメーターバー描画（横ゲージ）                               |
//+------------------------------------------------------------------+
void ScoreMeter(string name, int x, int y, int w, int h, int score, int maxScore)
{
   Rect(name + "_bg", x, y, x + w, y + h, C'20,25,32', InpColorBorder);
   int filled = (int)((double)score / maxScore * w);
   if(filled < 0) filled = 0;
   if(filled > w) filled = w;
   color clr = score >= 85 ? C'200,160,0' : score >= 70 ? C'88,166,255' : C'100,200,100';

   // スコア0でも必ずサイズ更新（古い値のバーが残るのを防ぐ）
   string fillName = PREFIX + name + "_fill";
   if(ObjectFind(0, fillName) < 0)
      ObjectCreate(0, fillName, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   int fillW = (filled > 2) ? filled - 2 : 1;
   color fillClr = (filled > 2) ? clr : C'20,25,32'; // 0点は背景色で不可視化
   ObjectSetInteger(0, fillName, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, fillName, OBJPROP_XDISTANCE, x + 1);
   ObjectSetInteger(0, fillName, OBJPROP_YDISTANCE, y + 1);
   ObjectSetInteger(0, fillName, OBJPROP_XSIZE, fillW);
   ObjectSetInteger(0, fillName, OBJPROP_YSIZE, h - 2);
   ObjectSetInteger(0, fillName, OBJPROP_BGCOLOR, fillClr);
   ObjectSetInteger(0, fillName, OBJPROP_BORDER_COLOR, fillClr);
   ObjectSetInteger(0, fillName, OBJPROP_BACK, true);
   ObjectSetInteger(0, fillName, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| メイン描画                                                        |
//+------------------------------------------------------------------+
void Redraw()
{
   int px = InpPanelX;
   int py = InpPanelY;
   int pw = 310;      // パネル幅
   int lh = 18;       // 行高さ
   int pad = 10;      // パディング
   int fs = InpFontSize;

   // === ダウ理論トレンド取得 ===
   int tD1  = DowTrend(PERIOD_D1);
   int tH4  = DowTrend(PERIOD_H4);
   int tH1  = DowTrend(PERIOD_H1);
   int tM15 = DowTrend(PERIOD_M15);

   // === 環境判定 ===
   string envText; color envColor;
   if(tD1 != 0 && tH4 == tD1 && tH1 == tD1)
   {
      envText = "3時間足一致 ★最高環境★";
      envColor = InpColorBull;
      if(tD1 == -1) envColor = InpColorBear;
   }
   else if(tD1 != 0 && tH4 == tD1)
   {
      envText = "日足+4H一致 → 押し目/戻り目待ち";
      envColor = tD1 == 1 ? InpColorBull : InpColorBear;
   }
   else if(tD1 != 0 && tH4 != 0 && tD1 != tH4)
   {
      envText = "⚠ 日足vs4H 逆行 (戦争状態)";
      envColor = InpColorRange;
   }
   else
   {
      envText = "方向感なし → 様子見";
      envColor = InpColorRange;
   }

   // === ATR取得 ===
   double atr[];
   ArraySetAsSeries(atr, true);
   double atrVal = 0;
   if(CopyBuffer(hATR_H1, 0, 1, 1, atr) >= 1) atrVal = atr[0];

   // === 損益履歴 ===
   int wins, losses;
   double maxDD;
   double totalPnL = GetHistoryPnL(wins, losses, maxDD);
   int totalTrades = wins + losses;
   double winRate = totalTrades > 0 ? (double)wins / totalTrades * 100 : 0;

   // === パネル全体の高さ計算 ===
   int rows = 22;
   int ph = rows * lh + pad * 3;
   int y = py;

   // === 背景 ===
   Rect("bg_main", px, py, px + pw, py + ph, InpColorBg, InpColorBorder);
   Rect("bg_title", px, py, px + pw, py + lh + pad, C'22,27,34', InpColorBorder);

   y = py + 5;

   // === タイトル ===
   Label("title", px + pad, y, "▶ 4P-Score FX ダッシュボード", InpColorTitle, fs + 1);
   y += lh + pad;

   // === セクション: トレンド状態 ===
   Rect("bg_sec1", px, y, px + pw, y + lh, C'22,27,34', InpColorBorder);
   Label("sec1", px + pad, y + 2, "── トレンド状態（ダウ理論）", InpColorBorder, fs - 1);
   y += lh + 3;

   // 各時間足の表示
   string tfLabels[4] = {"日足  D1", "4時間 H4", "1時間 H1", "15分  M15"};
   int    tfTrends[4];
   tfTrends[0] = tD1; tfTrends[1] = tH4; tfTrends[2] = tH1; tfTrends[3] = tM15;

   for(int i = 0; i < 4; i++)
   {
      int trend = tfTrends[i];
      string trendStr = trend == 1 ? "上昇 ▲" : trend == -1 ? "下降 ▼" : "不明  ─";
      color trendClr  = trend == 1 ? InpColorBull : trend == -1 ? InpColorBear : InpColorRange;

      Label("tf_" + i + "_label", px + pad, y + 2, tfLabels[i], InpColorText, fs);
      Label("tf_" + i + "_trend", px + 110, y + 2, trendStr, trendClr, fs);

      // トレンドバー
      TrendBar("tf_" + i + "_bar", px + 185, y + 4, 100, lh - 8, trend);
      y += lh;
   }
   y += 3;

   // === 環境判定 ===
   Rect("bg_env", px + pad, y - 2, px + pw - pad, y + lh + 2, C'22,27,34', envColor);
   Label("env_text", px + pad + 5, y + 1, envText, envColor, fs);
   y += lh + 6;

   // === セクション: 最新シグナル候補 ===
   Rect("bg_sec2", px, y, px + pw, y + lh, C'22,27,34', InpColorBorder);
   Label("sec2", px + pad, y + 2, "── 相場情報", InpColorBorder, fs - 1);
   y += lh + 3;

   // 現在価格・スプレッド
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double spread = (ask - bid) / SymbolInfoDouble(_Symbol, SYMBOL_POINT) / 10.0;
   Label("price_label", px + pad, y + 2, "現在値:", InpColorText, fs);
   Label("price_val",   px + 75, y + 2, DoubleToString(bid, digits), InpColorTitle, fs);
   Label("spread_label", px + 185, y + 2, StringFormat("スプレッド: %.1fpips", spread), InpColorRange, fs - 1);
   y += lh;

   // ATR
   string atrStr = atrVal > 0 ? DoubleToString(atrVal, digits) : "---";
   Label("atr_label", px + pad, y + 2, "ATR(H1,14):", InpColorText, fs);
   Label("atr_val",   px + 95, y + 2, atrStr, C'200,160,0', fs);
   y += lh;

   // MA20 vs 価格
   double ma1[];
   ArraySetAsSeries(ma1, true);
   double maH1Val = 0;
   if(CopyBuffer(hMA_H1, 0, 1, 1, ma1) >= 1) maH1Val = ma1[0];
   string maRel = maH1Val > 0 ? (bid > maH1Val ? "価格 > MA20 (強気)" : "価格 < MA20 (弱気)") : "---";
   color maRelClr = (maH1Val > 0 && bid > maH1Val) ? InpColorBull : InpColorBear;
   Label("ma_label", px + pad, y + 2, "H1 MA20:", InpColorText, fs);
   Label("ma_val",   px + 75, y + 2, maRel, maRelClr, fs - 1);
   y += lh + 3;

   // === セクション: スコアメーター ===
   Rect("bg_sec3", px, y, px + pw, y + lh, C'22,27,34', InpColorBorder);
   Label("sec3", px + pad, y + 2, "── 4P-Score スコアメーター（参考）", InpColorBorder, fs - 1);
   y += lh + 3;

   // スコア項目
   int baseScore = (tH4 != 0) ? 40 : 0;
   int s1 = (tD1 == tH4 && tD1 != 0) ? 20 : (tD1 == 0 && tH4 != 0) ? 5 : 0;
   int s2 = (tH4 != 0) ? OppForceScore(tH4) : 0; // 反対勢力までの実距離で採点
   int s3 = (tH1 == tH4 && tH4 != 0) ? 10 : 0;
   int s4 = 0;  // リトレースは個別判断（執行足の波形は目視確認）
   int totalScore = baseScore + s1 + s2 + s3 + s4;

   string scoreItems[5] = {"基本トリガー[40]", "日足合致[+20]", "反対勢力[+20]", "MA整列[+10]", "リトレース[+10]"};
   int    scoreVals[5];
   scoreVals[0] = baseScore; scoreVals[1] = s1; scoreVals[2] = s2; scoreVals[3] = s3; scoreVals[4] = s4;

   for(int i = 0; i < 5; i++)
   {
      int maxVal = (i == 0) ? 40 : (i < 3) ? 20 : 10;
      Label("score_" + i + "_l", px + pad, y + 2, scoreItems[i], InpColorText, fs - 1);
      ScoreMeter("score_" + i, px + 155, y + 3, 130, lh - 6, scoreVals[i], maxVal);
      Label("score_" + i + "_v", px + 292, y + 2, (string)scoreVals[i], InpColorTitle, fs - 1);
      y += lh;
   }

   // 合計スコア・グレード
   string grade = totalScore >= 85 ? "Sグレード" : totalScore >= 70 ? "Aグレード" : totalScore >= 55 ? "Bグレード" : "--";
   color gradeClr = totalScore >= 85 ? C'200,160,0' : totalScore >= 70 ? C'88,166,255' : totalScore >= 55 ? C'100,200,100' : InpColorRange;
   Label("total_score_l", px + pad, y + 2, StringFormat("概算スコア: %d点", totalScore), InpColorText, fs);
   Label("total_grade",   px + 160, y + 2, grade, gradeClr, fs);
   y += lh + 3;

   // === セクション: 損益履歴 ===
   Rect("bg_sec4", px, y, px + pw, y + lh, C'22,27,34', InpColorBorder);
   Label("sec4", px + pad, y + 2, StringFormat("── 損益履歴（直近%d日）", InpHistoryDays), InpColorBorder, fs - 1);
   y += lh + 3;

   if(totalTrades > 0)
   {
      color pnlClr = totalPnL >= 0 ? InpColorBull : InpColorBear;
      string pnlStr = StringFormat("%s%.2f", totalPnL >= 0 ? "+" : "", totalPnL);
      Label("hist_trades", px + pad, y + 2, StringFormat("取引数: %d回", totalTrades), InpColorText, fs);
      Label("hist_wr",     px + 130, y + 2, StringFormat("勝率: %.1f%%", winRate), InpColorText, fs);
      y += lh;
      Label("hist_pnl_l",  px + pad, y + 2, "純損益:", InpColorText, fs);
      Label("hist_pnl_v",  px + 60, y + 2, pnlStr, pnlClr, fs);
      Label("hist_dd",     px + 130, y + 2, StringFormat("最大DD: %.2f", maxDD), InpColorRange, fs);
   }
   else
   {
      Label("hist_none", px + pad, y + 2, "取引履歴なし（デモまたは未取引）", InpColorRange, fs);
   }
   y += lh + 3;

   // === フッター ===
   Label("footer", px + pad, y + 2, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), InpColorRange, fs - 1);

   ChartRedraw(0);
}
//+------------------------------------------------------------------+
