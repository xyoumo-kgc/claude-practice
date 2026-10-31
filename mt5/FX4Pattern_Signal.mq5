//+------------------------------------------------------------------+
//|  FX4Pattern_Signal.mq5                                           |
//|  オリジナル・エントリーシグナルシステム「4P-Score」              |
//|                                                                  |
//|  【コンセプト】                                                   |
//|  「4つの鉄板エントリーパターン解説マニュアル」の手法を            |
//|  ダウ理論ベースで忠実に実装したシグナル検出システム。            |
//|                                                                  |
//|  従来EA（FX4Pattern_EA）との違い:                                |
//|   ・MAスロープではなく実際のスイング高値・安値で                 |
//|     「高値切り下げ＋安値更新」（ダウ理論の転換）を検出           |
//|   ・パターン①②③を同時監視（④-Bは情報通知のみ）               |
//|   ・要素①（日足合致）と要素②（反対勢力）を点数化               |
//|   ・0〜100点のスコアでシグナルをS/A/Bグレード判定                |
//|   ・スマホMT5アプリへのプッシュ通知に対応                        |
//|                                                                  |
//|  【スコア配点】                                                   |
//|   基本トリガー成立（ダウ理論転換）          : 40点               |
//|   要素① 日足の方向と合致                    : +20点（逆行=却下） |
//|   要素② 反対勢力までの距離（ATR比）         : +20点              |
//|   MA整列（上位足MAと同方向に拡散）          : +10点              |
//|   押し・戻りの深さ（30〜70%リトレース）     : +10点              |
//|                                                                  |
//|  【グレード】 S: 85点以上 / A: 70点以上 / B: 55点以上            |
//|                                                                  |
//|  【推奨】 H1チャートにアタッチ（全時間足を内部で自動監視）       |
//+------------------------------------------------------------------+
#property copyright "FX 4Pattern Original Signal System"
#property version   "1.00"
#property description "ダウ理論ベース 4つの鉄板パターン シグナルシステム 4P-Score"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| 入力パラメータ                                                    |
//+------------------------------------------------------------------+
input group "=== シグナル検出 ==="
input int    InpSwingDepth    = 3;     // スイング判定の左右バー数（フラクタル深さ）
input int    InpLookbackBars  = 400;   // スイング探索範囲（バー数）
input bool   InpEnableP1      = true;  // パターン①: 4時間足レベルの押し目・戻り目
input bool   InpEnableP2      = true;  // パターン②: 1時間足レベルの押し目・戻り目
input bool   InpEnableP3      = true;  // パターン③: 日足レベルの押し目・戻り目
input bool   InpNotifyP4B     = true;  // パターン④-B: 日足逆行転換の情報通知
input int    InpMinScore      = 70;    // 通知する最低スコア（70 = Aグレード以上）

input group "=== 要素②（反対勢力）判定 ==="
input double InpOppForceVetoATR = 1.0; // 反対勢力がATR×この値より近ければ却下
input double InpOppForceFullATR = 3.0; // ATR×この値以上離れていれば満点

input group "=== 通知 ==="
input bool   InpPushNotify    = true;  // スマホへプッシュ通知（MT5アプリ）
input bool   InpAlertPopup    = true;  // PC上でアラートポップアップ
input bool   InpShowPanel     = true;  // チャート左上に状況パネルを表示

input group "=== 時間フィルター（マニュアル: 週末持ち越しなし） ==="
input int    InpStartHour     = 2;     // 取引開始時間（サーバー時刻）
input int    InpEndHour       = 22;    // 取引終了時間（サーバー時刻）
input bool   InpNoFridayNight = true;  // 金曜21時以降は新規シグナル・エントリーなし
input bool   InpFridayClose   = true;  // 金曜22時に自動売買ポジションを強制クローズ
input int    InpCooldownBars  = 10;    // 同一パターンの再シグナル禁止バー数（執行足）

input group "=== 自動売買（オプション・デフォルトOFF） ==="
input bool   InpAutoTrade     = false; // Sグレードシグナルで自動エントリー
input int    InpAutoMinScore  = 85;    // 自動売買する最低スコア
input double InpRiskPercent   = 1.0;   // 1トレードのリスク率（口座残高の%）
input double InpRiskReward    = 2.0;   // リスクリワード比
input double InpSL_BufferATR  = 0.3;   // SL = スイング高値/安値 ± ATR×この値
input int    InpMaxPositions  = 1;     // 最大同時保有ポジション数
input int    InpMagicNumber   = 20260002; // マジックナンバー

//+------------------------------------------------------------------+
//| 定義                                                              |
//+------------------------------------------------------------------+
struct Swing
{
   double   price;
   int      bar;
   datetime time;
};

struct SignalInfo
{
   int      pattern;     // 1, 2, 3, 4 (=④-B)
   int      dir;         // +1 買い / -1 売り
   int      score;
   string   grade;
   string   detail;
   datetime time;
};

CTrade        Trade;
CPositionInfo PositionInfo;

// インジケーターハンドル（時間足ごと）
int hMA_M15, hMA_H1, hMA_H4, hMA_D1;
int hATR_M15, hATR_H1, hATR_H4, hATR_D1;

// 新バー検出用
datetime g_lastBar_M15 = 0, g_lastBar_H1 = 0, g_lastBar_H4 = 0;

// 直近シグナル（パネル表示用）
SignalInfo g_lastSignal;
string     g_panelStatus = "";

// パターンごとの直近シグナル時刻（重複通知防止）
datetime g_lastSignalTime[5] = {0, 0, 0, 0, 0};

//+------------------------------------------------------------------+
//| 初期化                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   hMA_M15 = iMA(_Symbol, PERIOD_M15, 20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_H1  = iMA(_Symbol, PERIOD_H1,  20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_H4  = iMA(_Symbol, PERIOD_H4,  20, 0, MODE_SMA, PRICE_CLOSE);
   hMA_D1  = iMA(_Symbol, PERIOD_D1,  20, 0, MODE_SMA, PRICE_CLOSE);

   hATR_M15 = iATR(_Symbol, PERIOD_M15, 14);
   hATR_H1  = iATR(_Symbol, PERIOD_H1,  14);
   hATR_H4  = iATR(_Symbol, PERIOD_H4,  14);
   hATR_D1  = iATR(_Symbol, PERIOD_D1,  14);

   if(hMA_M15 == INVALID_HANDLE || hMA_H1 == INVALID_HANDLE ||
      hMA_H4  == INVALID_HANDLE || hMA_D1 == INVALID_HANDLE ||
      hATR_M15 == INVALID_HANDLE || hATR_H1 == INVALID_HANDLE ||
      hATR_H4  == INVALID_HANDLE || hATR_D1 == INVALID_HANDLE)
   {
      Alert("4P-Score: インジケーター初期化失敗");
      return INIT_FAILED;
   }

   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetDeviationInPoints(20);
   Trade.SetTypeFilling(ORDER_FILLING_IOC);

   g_lastSignal.score = -1;

   PrintFormat("=== 4P-Score シグナルシステム起動 [%s] ===", _Symbol);
   PrintFormat("監視パターン: ①%s ②%s ③%s ④-B通知%s | 最低スコア=%d",
               InpEnableP1 ? "ON" : "OFF", InpEnableP2 ? "ON" : "OFF",
               InpEnableP3 ? "ON" : "OFF", InpNotifyP4B ? "ON" : "OFF",
               InpMinScore);
   PrintFormat("自動売買: %s（最低スコア=%d）",
               InpAutoTrade ? "有効" : "無効", InpAutoMinScore);

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   Comment("");
   IndicatorRelease(hMA_M15);  IndicatorRelease(hMA_H1);
   IndicatorRelease(hMA_H4);   IndicatorRelease(hMA_D1);
   IndicatorRelease(hATR_M15); IndicatorRelease(hATR_H1);
   IndicatorRelease(hATR_H4);  IndicatorRelease(hATR_D1);
}

//+------------------------------------------------------------------+
//| メインループ                                                      |
//+------------------------------------------------------------------+
void OnTick()
{
   bool newM15 = false, newH1 = false, newH4 = false;

   datetime t;
   t = iTime(_Symbol, PERIOD_M15, 0);
   if(t != g_lastBar_M15) { g_lastBar_M15 = t; newM15 = true; }
   t = iTime(_Symbol, PERIOD_H1, 0);
   if(t != g_lastBar_H1)  { g_lastBar_H1 = t;  newH1 = true; }
   t = iTime(_Symbol, PERIOD_H4, 0);
   if(t != g_lastBar_H4)  { g_lastBar_H4 = t;  newH4 = true; }

   // 金曜深夜の強制クローズ（マニュアル: 週末持ち越しなし）
   if(InpFridayClose && newM15) CloseBeforeWeekend();

   // 時間フィルター（時間外はシグナル検出もスキップ）
   if(IsSignalTime())
   {
      // 各パターンは執行足の新バー確定時に判定（リペイント防止）
      if(newM15 && InpEnableP2) CheckPattern(2, PERIOD_H1, PERIOD_M15);
      if(newH1  && InpEnableP1) CheckPattern(1, PERIOD_H4, PERIOD_H1);
      if(newH4  && InpEnableP3) CheckPattern(3, PERIOD_D1, PERIOD_H4);
      if(newH4  && InpNotifyP4B) CheckPattern4B();
   }

   if(InpShowPanel && (newM15 || newH1 || newH4)) UpdatePanel();
}

//+------------------------------------------------------------------+
//| シグナル検出を行う時間帯かどうか                                 |
//+------------------------------------------------------------------+
bool IsSignalTime()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(dt.day_of_week == 0 || dt.day_of_week == 6) return false;          // 土日
   if(InpNoFridayNight && dt.day_of_week == 5 && dt.hour >= 21) return false; // 金曜夜
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;     // 時間帯

   return true;
}

//+------------------------------------------------------------------+
//| 金曜22時以降に自動売買ポジションをクローズ                       |
//+------------------------------------------------------------------+
void CloseBeforeWeekend()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_week != 5 || dt.hour < 22) return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!PositionInfo.SelectByIndex(i)) continue;
      if(PositionInfo.Symbol() != _Symbol || PositionInfo.Magic() != InpMagicNumber) continue;
      if(Trade.PositionClose(PositionInfo.Ticket()))
         PrintFormat("[4P-Score] 週末持ち越し回避: ポジション #%I64u をクローズ",
                     PositionInfo.Ticket());
   }
}

//+------------------------------------------------------------------+
//| スイング高値の検出（新しい順に格納）                             |
//+------------------------------------------------------------------+
int FindSwingHighs(ENUM_TIMEFRAMES tf, Swing &out[])
{
   int n = 0, maxKeep = ArraySize(out);
   int bars = MathMin(InpLookbackBars, iBars(_Symbol, tf) - InpSwingDepth - 1);
   for(int i = InpSwingDepth + 1; i < bars && n < maxKeep; i++)
   {
      double h = iHigh(_Symbol, tf, i);
      bool isSwing = true;
      for(int k = 1; k <= InpSwingDepth && isSwing; k++)
      {
         if(h <= iHigh(_Symbol, tf, i - k)) isSwing = false;
         if(h <  iHigh(_Symbol, tf, i + k)) isSwing = false;
      }
      if(isSwing)
      {
         out[n].price = h;
         out[n].bar   = i;
         out[n].time  = iTime(_Symbol, tf, i);
         n++;
      }
   }
   return n;
}

//+------------------------------------------------------------------+
//| スイング安値の検出（新しい順に格納）                             |
//+------------------------------------------------------------------+
int FindSwingLows(ENUM_TIMEFRAMES tf, Swing &out[])
{
   int n = 0, maxKeep = ArraySize(out);
   int bars = MathMin(InpLookbackBars, iBars(_Symbol, tf) - InpSwingDepth - 1);
   for(int i = InpSwingDepth + 1; i < bars && n < maxKeep; i++)
   {
      double l = iLow(_Symbol, tf, i);
      bool isSwing = true;
      for(int k = 1; k <= InpSwingDepth && isSwing; k++)
      {
         if(l >= iLow(_Symbol, tf, i - k)) isSwing = false;
         if(l >  iLow(_Symbol, tf, i + k)) isSwing = false;
      }
      if(isSwing)
      {
         out[n].price = l;
         out[n].bar   = i;
         out[n].time  = iTime(_Symbol, tf, i);
         n++;
      }
   }
   return n;
}

//+------------------------------------------------------------------+
//| ダウ理論によるトレンド判定                                       |
//|  +1: 安値切り上げ＋高値切り上げ（上昇トレンド）                  |
//|  -1: 高値切り下げ＋安値切り下げ（下降トレンド）                  |
//|   0: どちらでもない（トレンド終了・レンジ・判定不能）            |
//+------------------------------------------------------------------+
int DowTrend(ENUM_TIMEFRAMES tf)
{
   Swing highs[4], lows[4];
   int nH = FindSwingHighs(tf, highs);
   int nL = FindSwingLows(tf, lows);
   if(nH < 2 || nL < 2) return 0;

   bool hh = highs[0].price > highs[1].price; // 高値切り上げ
   bool hl = lows[0].price  > lows[1].price;  // 安値切り上げ
   bool lh = highs[0].price < highs[1].price; // 高値切り下げ
   bool ll = lows[0].price  < lows[1].price;  // 安値切り下げ

   if(hh && hl) return  1;
   if(lh && ll) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| 執行足のダウ理論転換イベント検出                                 |
//|  dir=-1（売り）: 高値切り下げ済み ＋ 直近スイング安値を         |
//|                  確定バー[1]が初めて下抜けた瞬間                 |
//|  dir=+1（買い）: 安値切り上げ済み ＋ 直近スイング高値を         |
//|                  確定バー[1]が初めて上抜けた瞬間                 |
//|  戻り値: イベント成立なら true（brokenLevel に転換確定水準）     |
//+------------------------------------------------------------------+
bool ReversalEvent(ENUM_TIMEFRAMES tf, int dir, double &brokenLevel, double &swingExtreme)
{
   Swing highs[4], lows[4];
   int nH = FindSwingHighs(tf, highs);
   int nL = FindSwingLows(tf, lows);
   if(nH < 2 || nL < 2) return false;

   double c1 = iClose(_Symbol, tf, 1);
   double c2 = iClose(_Symbol, tf, 2);

   if(dir == -1)
   {
      // 売り: 戻り目の高値（highs[0]）がその前の高値より低い（高値切り下げ）
      //       かつ 戻り目の起点となった安値（lows[0]）を今まさに下抜けた
      bool lowerHigh   = highs[0].price < highs[1].price;
      bool sequenceOK  = lows[0].bar > highs[0].bar; // 安値→戻り高値の順に形成
      bool freshBreak  = (c2 >= lows[0].price) && (c1 < lows[0].price);
      if(lowerHigh && sequenceOK && freshBreak)
      {
         brokenLevel  = lows[0].price;
         swingExtreme = highs[0].price; // SL基準 = 直近戻り高値
         return true;
      }
   }
   else
   {
      // 買い: 押し目の安値（lows[0]）がその前の安値より高い（安値切り上げ）
      //       かつ 押し目の起点となった高値（highs[0]）を今まさに上抜けた
      bool higherLow   = lows[0].price > lows[1].price;
      bool sequenceOK  = highs[0].bar > lows[0].bar; // 高値→押し安値の順に形成
      bool freshBreak  = (c2 <= highs[0].price) && (c1 > highs[0].price);
      if(higherLow && sequenceOK && freshBreak)
      {
         brokenLevel  = highs[0].price;
         swingExtreme = lows[0].price; // SL基準 = 直近押し安値
         return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| ATR値取得                                                         |
//+------------------------------------------------------------------+
double GetATR(ENUM_TIMEFRAMES tf)
{
   int handle = (tf == PERIOD_M15) ? hATR_M15 :
                (tf == PERIOD_H1)  ? hATR_H1  :
                (tf == PERIOD_H4)  ? hATR_H4  : hATR_D1;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, 1, 1, buf) < 1) return 0;
   return buf[0];
}

//+------------------------------------------------------------------+
//| MA値取得                                                          |
//+------------------------------------------------------------------+
double GetMA(ENUM_TIMEFRAMES tf, int shift)
{
   int handle = (tf == PERIOD_M15) ? hMA_M15 :
                (tf == PERIOD_H1)  ? hMA_H1  :
                (tf == PERIOD_H4)  ? hMA_H4  : hMA_D1;
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, shift, 1, buf) < 1) return 0;
   return buf[0];
}

//+------------------------------------------------------------------+
//| 要素②: 反対勢力までの距離を採点（0〜20点、近すぎは-1=却下）     |
//|  売り: 直下のサポート（上位足スイング安値・日足MA）              |
//|  買い: 直上のレジスタンス（上位足スイング高値・日足MA）          |
//+------------------------------------------------------------------+
int ScoreOppForce(int dir, ENUM_TIMEFRAMES bigTF, ENUM_TIMEFRAMES execTF, double atrBig, string &note)
{
   double price = iClose(_Symbol, execTF, 1);
   double nearest = 0;
   bool   found = false;

   // 上位足（bigTF と 日足）のスイングを反対勢力候補とする
   ENUM_TIMEFRAMES tfs[2];
   tfs[0] = bigTF;
   tfs[1] = PERIOD_D1;

   for(int t = 0; t < 2; t++)
   {
      if(t == 1 && bigTF == PERIOD_D1) break; // 重複回避
      Swing highs[4], lows[4];
      int nH = FindSwingHighs(tfs[t], highs);
      int nL = FindSwingLows(tfs[t], lows);

      if(dir == -1) // 売り → 直下のサポートを探す
      {
         for(int i = 0; i < nL; i++)
            if(lows[i].price < price)
               if(!found || lows[i].price > nearest) { nearest = lows[i].price; found = true; }
      }
      else          // 買い → 直上のレジスタンスを探す
      {
         for(int i = 0; i < nH; i++)
            if(highs[i].price > price)
               if(!found || highs[i].price < nearest) { nearest = highs[i].price; found = true; }
      }
   }

   // 日足MA20も反対勢力候補
   double maD1 = GetMA(PERIOD_D1, 1);
   if(maD1 > 0)
   {
      if(dir == -1 && maD1 < price)
         if(!found || maD1 > nearest) { nearest = maD1; found = true; }
      if(dir == 1 && maD1 > price)
         if(!found || maD1 < nearest) { nearest = maD1; found = true; }
   }

   if(!found || atrBig <= 0)
   {
      note = "反対勢力なし（視界良好）";
      return 20;
   }

   double distATR = MathAbs(price - nearest) / atrBig;
   note = StringFormat("最寄り反対勢力 %.2f（距離 %.1f ATR）", nearest, distATR);

   if(distATR < InpOppForceVetoATR) return -1;  // 近すぎ → エントリー却下
   if(distATR >= InpOppForceFullATR) return 20;
   if(distATR >= (InpOppForceVetoATR + InpOppForceFullATR) / 2.0) return 10;
   return 5;
}

//+------------------------------------------------------------------+
//| MA整列スコア（0〜10点）                                          |
//|  執行足の上の時間足とさらに上の時間足のMAが                      |
//|  シグナル方向に整列・拡散しているか                              |
//+------------------------------------------------------------------+
int ScoreMAAlign(int dir, ENUM_TIMEFRAMES bigTF, ENUM_TIMEFRAMES execTF)
{
   double price  = iClose(_Symbol, execTF, 1);
   double maExec = GetMA(execTF, 1);
   double maBig  = GetMA(bigTF, 1);
   double maBigPrev = GetMA(bigTF, 4);
   if(maExec <= 0 || maBig <= 0 || maBigPrev <= 0) return 0;

   if(dir == -1)
   {
      // 売り: レート < 執行足MA < 上位足MA かつ 上位足MAが下向き
      if(price < maExec && maExec < maBig && maBig < maBigPrev) return 10;
      if(price < maBig && maBig < maBigPrev) return 5;
   }
   else
   {
      if(price > maExec && maExec > maBig && maBig > maBigPrev) return 10;
      if(price > maBig && maBig > maBigPrev) return 5;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| 押し・戻りの深さスコア（0〜10点）                                |
//|  直前波の30〜70%リトレースが理想的な押し目・戻り目               |
//+------------------------------------------------------------------+
int ScoreRetracement(int dir, ENUM_TIMEFRAMES execTF)
{
   Swing highs[4], lows[4];
   int nH = FindSwingHighs(execTF, highs);
   int nL = FindSwingLows(execTF, lows);
   if(nH < 2 || nL < 1) return 0;

   double waveSize, retrace;
   if(dir == -1)
   {
      // 売り: 下降波 highs[1]→lows[0] に対する戻り highs[0]
      waveSize = highs[1].price - lows[0].price;
      retrace  = highs[0].price - lows[0].price;
   }
   else
   {
      // 買い: 上昇波 lows[1]→highs[0] に対する押し lows[0]
      if(nL < 2) return 0;
      waveSize = highs[0].price - lows[1].price;
      retrace  = highs[0].price - lows[0].price;
   }
   if(waveSize <= 0) return 0;

   double ratio = retrace / waveSize;
   if(ratio >= 0.30 && ratio <= 0.70) return 10; // 理想的な深さ
   if(ratio > 0.70 && ratio <= 0.85)  return 5;  // やや深いが許容
   return 0; // 浅すぎ（だましの可能性）または深すぎ（転換リスク）
}

//+------------------------------------------------------------------+
//| パターン①②③の判定とスコアリング                               |
//+------------------------------------------------------------------+
void CheckPattern(int patternNo, ENUM_TIMEFRAMES bigTF, ENUM_TIMEFRAMES execTF)
{
   // クールダウン: 同一パターンの連続シグナルを抑止
   datetime barSec = (datetime)(PeriodSeconds(execTF) * InpCooldownBars);
   if(TimeCurrent() - g_lastSignalTime[patternNo] < barSec) return;

   // 大きな流れ（ダウ理論）
   int bigTrend = DowTrend(bigTF);
   if(bigTrend == 0) return;

   int dir = bigTrend; // トレンドフォローのみ: 大きな流れの方向にしか入らない

   // 執行足の転換イベント
   double brokenLevel, swingExtreme;
   if(!ReversalEvent(execTF, dir, brokenLevel, swingExtreme)) return;

   // ===== スコアリング =====
   int score = 40; // 基本トリガー成立
   string detail = StringFormat("ダウ転換確定 %.2f%s抜け [+40]",
                                brokenLevel, dir == -1 ? "下" : "上");

   // --- 要素①: 日足の方向と合致しているか ---
   int dayTrend = DowTrend(PERIOD_D1);
   if(bigTF == PERIOD_D1)
   {
      score += 20;
      detail += " | 日足=大きな流れ [+20]";
   }
   else if(dayTrend == dir)
   {
      score += 20;
      detail += " | 要素①日足合致 [+20]";
   }
   else if(dayTrend == 0)
   {
      score += 5;
      detail += " | 日足レンジ（要注意）[+5]";
   }
   else
   {
      // 日足と真逆 = 戦争状態 → マニュアルの教え通りエントリー却下
      PrintFormat("[4P-Score] P%d %s シグナル候補却下: 日足と逆行（戦争状態）",
                  patternNo, dir == 1 ? "買い" : "売り");
      return;
   }

   // --- 要素②: 反対勢力までの距離 ---
   double atrBig = GetATR(bigTF);
   string oppNote;
   int oppScore = ScoreOppForce(dir, bigTF, execTF, atrBig, oppNote);
   if(oppScore < 0)
   {
      PrintFormat("[4P-Score] P%d シグナル候補却下: 反対勢力が近すぎる（%s）",
                  patternNo, oppNote);
      return;
   }
   score += oppScore;
   detail += StringFormat(" | 要素②%s [+%d]", oppNote, oppScore);

   // --- MA整列 ---
   int maScore = ScoreMAAlign(dir, bigTF, execTF);
   score += maScore;
   if(maScore > 0) detail += StringFormat(" | MA整列 [+%d]", maScore);

   // --- 押し・戻りの深さ ---
   int rtScore = ScoreRetracement(dir, execTF);
   score += rtScore;
   if(rtScore > 0) detail += StringFormat(" | リトレース良好 [+%d]", rtScore);

   // ===== グレード判定・通知 =====
   if(score < InpMinScore) return;

   string grade = (score >= 85) ? "S" : (score >= 70) ? "A" : "B";
   EmitSignal(patternNo, dir, score, grade, detail, swingExtreme);
}

//+------------------------------------------------------------------+
//| パターン④-B: 日足に逆行する4時間足転換（情報通知のみ）          |
//|  日足の押し目・戻り目形成の「起点」の可能性を知らせる            |
//+------------------------------------------------------------------+
void CheckPattern4B()
{
   // クールダウン（パターン④は index 4）
   datetime barSec = (datetime)(PeriodSeconds(PERIOD_H4) * InpCooldownBars);
   if(TimeCurrent() - g_lastSignalTime[4] < barSec) return;

   int dayTrend = DowTrend(PERIOD_D1);
   if(dayTrend == 0) return;

   // 日足と逆方向への4H転換を検出
   int counterDir = -dayTrend;
   double brokenLevel, swingExtreme;
   if(!ReversalEvent(PERIOD_H4, counterDir, brokenLevel, swingExtreme)) return;

   string msg = StringFormat(
      "[4P-Score %s] パターン④-B検出: 4時間足が日足（%s）に逆行して転換。"
      "日足の%s形成の起点の可能性 → この逆行は追わず、%sの準備を",
      _Symbol,
      dayTrend == 1 ? "上昇" : "下降",
      dayTrend == 1 ? "押し目" : "戻り目",
      dayTrend == 1 ? "押し目買い" : "戻り売り");

   Print(msg);
   if(InpPushNotify) SendNotification(msg);
   g_lastSignalTime[4] = TimeCurrent();
}

//+------------------------------------------------------------------+
//| シグナル発火（通知＋オプションで自動売買）                       |
//+------------------------------------------------------------------+
void EmitSignal(int patternNo, int dir, int score, string grade,
                string detail, double swingExtreme)
{
   string dirStr = (dir == 1) ? "買い(LONG)" : "売り(SHORT)";
   string patternName =
      (patternNo == 1) ? "①4時間足レベルの押し目・戻り目" :
      (patternNo == 2) ? "②1時間足レベルの押し目・戻り目" :
                         "③日足レベルの押し目・戻り目";

   double price = SymbolInfoDouble(_Symbol, dir == 1 ? SYMBOL_ASK : SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   string msg = StringFormat(
      "[4P-Score %s] %sグレード(%d点) %s\nパターン%s\n現在値: %s\nSL目安: %s（直近スイングの向こう側）",
      _Symbol, grade, score, dirStr, patternName,
      DoubleToString(price, digits), DoubleToString(swingExtreme, digits));

   Print(msg);
   Print("内訳: ", detail);
   if(InpAlertPopup) Alert(msg);
   if(InpPushNotify) SendNotification(msg);

   g_lastSignal.pattern = patternNo;
   g_lastSignal.dir     = dir;
   g_lastSignal.score   = score;
   g_lastSignal.grade   = grade;
   g_lastSignal.detail  = detail;
   g_lastSignal.time    = TimeCurrent();
   g_lastSignalTime[patternNo] = TimeCurrent();

   // 自動売買（オプション）
   if(InpAutoTrade && score >= InpAutoMinScore)
      OpenPosition(dir, swingExtreme);
}

//+------------------------------------------------------------------+
//| ポジションオープン（SLは直近スイングの向こう側）                 |
//+------------------------------------------------------------------+
void OpenPosition(int dir, double swingExtreme)
{
   if(CountPositions() >= InpMaxPositions) return;

   double atr = GetATR(PERIOD_H1);
   if(atr <= 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = (dir == 1) ? ask : bid;

   // SL = 直近押し安値/戻り高値 ± バッファ（マニュアル準拠）
   double sl = (dir == 1) ? swingExtreme - atr * InpSL_BufferATR
                          : swingExtreme + atr * InpSL_BufferATR;
   double slDist = MathAbs(entry - sl);

   // SLが近すぎる場合はATR×2にフォールバック
   if(slDist < atr) { slDist = atr * 2.0; sl = (dir == 1) ? entry - slDist : entry + slDist; }

   double tp = (dir == 1) ? entry + slDist * InpRiskReward
                          : entry - slDist * InpRiskReward;

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);

   double lots = CalcLotSize(slDist);
   if(lots <= 0) return;

   string comment = StringFormat("4PS_%s_%d", dir == 1 ? "BUY" : "SELL", g_lastSignal.score);
   bool ok = (dir == 1)
      ? Trade.Buy(lots,  _Symbol, 0, sl, tp, comment)
      : Trade.Sell(lots, _Symbol, 0, sl, tp, comment);

   if(!ok)
      PrintFormat("注文失敗 [%d]: %s", GetLastError(), Trade.ResultComment());
}

//+------------------------------------------------------------------+
//| このEAのポジション数                                             |
//+------------------------------------------------------------------+
int CountPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionInfo.SelectByIndex(i))
         if(PositionInfo.Symbol() == _Symbol && PositionInfo.Magic() == InpMagicNumber)
            count++;
   return count;
}

//+------------------------------------------------------------------+
//| ロットサイズ計算（リスク率ベース）                               |
//+------------------------------------------------------------------+
double CalcLotSize(double slDistPrice)
{
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;

   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double minLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot    = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(tickSize <= 0 || tickValue <= 0) return minLot;

   double slValuePerLot = (slDistPrice / tickSize) * tickValue;
   if(slValuePerLot <= 0) return minLot;

   double lots = MathFloor((riskMoney / slValuePerLot) / lotStep) * lotStep;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| チャート左上の状況パネル                                         |
//+------------------------------------------------------------------+
void UpdatePanel()
{
   int dT = DowTrend(PERIOD_D1);
   int hT = DowTrend(PERIOD_H4);
   int oT = DowTrend(PERIOD_H1);

   string txt = "═══ 4P-Score シグナルシステム ═══\n";
   txt += StringFormat("銘柄: %s\n", _Symbol);
   txt += StringFormat("日足   : %s\n", TrendStr(dT));
   txt += StringFormat("4時間足: %s\n", TrendStr(hT));
   txt += StringFormat("1時間足: %s\n", TrendStr(oT));

   if(dT != 0 && hT == dT)
      txt += StringFormat("環境: %s方向で一致（%s待ち）\n",
                          dT == 1 ? "上" : "下",
                          dT == 1 ? "押し目買い" : "戻り売り");
   else if(dT != 0 && hT == -dT)
      txt += "環境: 日足vs4H 逆行中（戦争状態 → 様子見）\n";
   else
      txt += "環境: 方向感なし（様子見）\n";

   if(g_lastSignal.score >= 0)
      txt += StringFormat("直近シグナル: P%d %s %sグレード(%d点) %s\n",
                          g_lastSignal.pattern,
                          g_lastSignal.dir == 1 ? "買い" : "売り",
                          g_lastSignal.grade, g_lastSignal.score,
                          TimeToString(g_lastSignal.time, TIME_DATE | TIME_MINUTES));
   else
      txt += "直近シグナル: なし\n";

   Comment(txt);
}

string TrendStr(int t)
{
   return (t == 1) ? "上昇（安値切上げ+高値更新）" :
          (t == -1) ? "下降（高値切下げ+安値更新）" : "レンジ/不明瞭";
}
//+------------------------------------------------------------------+
