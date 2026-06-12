"""
4P-Score オリジナルシグナルシステム バックテスト（シミュレーション版）

FX4Pattern_Signal.mq5 と同じロジックをPythonで再現し、
従来のMAスロープ版（FX4Pattern_EA）と性能を比較する。

【4P-Scoreの特徴（従来版との違い）】
  ・ダウ理論スイング検出（高値切り下げ＋安値更新の実検出）
  ・要素①（日足合致）: 逆行なら却下、合致で+20点
  ・要素②（反対勢力）: 上位足スイングまでの距離をATR比で採点
  ・MA整列 +10点 / リトレース深さ(30-70%) +10点
  ・スコア70点（Aグレード）以上のみエントリー
  ・SLは直近スイングの向こう側（マニュアル準拠）

※ネットワーク制限のため合成OHLCデータを使用（fx_backtest_sim.py と同一生成器）
"""
import warnings; warnings.filterwarnings('ignore')
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

# ============================================================
# 通貨ペアの統計特性（fx_backtest_sim.py と同一）
# ============================================================
PAIR_CONFIG = {
    'USDJPY': {'start_price': 107.0,  'annual_vol': 0.085, 'annual_drift':  0.06, 'trend_persistence': 0.65},
    'EURUSD': {'start_price': 1.2100, 'annual_vol': 0.072, 'annual_drift': -0.03, 'trend_persistence': 0.55},
    'GBPUSD': {'start_price': 1.3700, 'annual_vol': 0.088, 'annual_drift': -0.02, 'trend_persistence': 0.58},
    'XAUUSD': {'start_price': 1850.0, 'annual_vol': 0.140, 'annual_drift':  0.12, 'trend_persistence': 0.60},
}

BACKTEST_YEARS = 3
HOURS_PER_YEAR = 252 * 6
RISK_REWARD = 2.0
SWING_DEPTH = 3
# 最低スコア: 引数で変更可（例: python fx_signal_backtest.py 55）
MIN_SCORE = int(sys.argv[1]) if len(sys.argv) > 1 else 70
OPP_VETO_ATR = 1.0       # 反対勢力がこれより近いと却下
OPP_FULL_ATR = 3.0       # これ以上離れていれば満点
SL_BUFFER_ATR = 0.3      # SL = スイング ± ATR×0.3
MA_SLOPE_WINDOW = 5      # ベースライン用


# ============================================================
# 合成OHLCデータ生成（fx_backtest_sim.py と同一ロジック）
# ============================================================
def generate_ohlc(config, n_hours):
    annual_vol = config['annual_vol']
    annual_drift = config['annual_drift']
    trend_persistence = config['trend_persistence']
    start_price = config['start_price']

    dt = 1 / HOURS_PER_YEAR
    hourly_vol = annual_vol * np.sqrt(dt)
    hourly_drift = annual_drift * dt

    regime = np.zeros(n_hours)
    regime[0] = np.random.choice([1, -1, 0], p=[0.35, 0.30, 0.35])
    regime_duration = 0
    for i in range(1, n_hours):
        regime_duration += 1
        if regime_duration > 40:
            if np.random.random() < (1 - trend_persistence):
                regime[i] = np.random.choice([1, -1, 0], p=[0.35, 0.30, 0.35])
                regime_duration = 0
            else:
                regime[i] = regime[i-1]
        else:
            regime[i] = regime[i-1]

    closes = np.zeros(n_hours)
    closes[0] = start_price
    for i in range(1, n_hours):
        trend_boost = regime[i] * hourly_vol * 0.3
        shock = np.random.normal(hourly_drift + trend_boost, hourly_vol)
        closes[i] = closes[i-1] * np.exp(shock)

    intra_vol = hourly_vol * start_price
    highs = closes + np.abs(np.random.normal(0, intra_vol * 0.6, n_hours))
    lows  = closes - np.abs(np.random.normal(0, intra_vol * 0.6, n_hours))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]

    idx = []
    dt_curr = datetime(2021, 1, 4, 0, 0)
    while len(idx) < n_hours:
        if dt_curr.weekday() < 5:
            idx.append(dt_curr)
        dt_curr += timedelta(hours=1)

    return pd.DataFrame({
        'Open': opens[:len(idx)], 'High': highs[:len(idx)],
        'Low': lows[:len(idx)], 'Close': closes[:len(idx)],
    }, index=idx[:n_hours])


def resample(df_1h, rule):
    return df_1h.resample(rule).agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'), Close=('Close', 'last'),
    ).dropna()


def add_atr(df, period=14):
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    df['ATR'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(period).mean()
    return df


# ============================================================
# ダウ理論スイング検出（MQL5版 FindSwingHighs/Lows と同等）
# ============================================================
def find_swings(high, low, depth=SWING_DEPTH):
    """各バー時点で確定済みのスイング高値・安値リストを構築。
    戻り値: swings_high[i], swings_low[i] = バーiの時点で確定している
            スイングの(値, バー位置)リスト（新しい順）"""
    n = len(high)
    swing_high_at = [None] * n  # (price, bar) 確定したバーで記録
    swing_low_at = [None] * n

    for i in range(depth, n - depth):
        h = high[i]
        if all(h > high[i+k] for k in range(1, depth+1)) and \
           all(h >= high[i-k] for k in range(1, depth+1)):
            swing_high_at[i + depth] = (h, i)  # depth本後のバーで確定
        l = low[i]
        if all(l < low[i+k] for k in range(1, depth+1)) and \
           all(l <= low[i-k] for k in range(1, depth+1)):
            swing_low_at[i + depth] = (l, i)

    return swing_high_at, swing_low_at


class SwingTracker:
    """バーを進めながら確定済みスイングを蓄積し、ダウ理論トレンドを返す"""
    def __init__(self, swing_high_at, swing_low_at, keep=6):
        self.sh_at, self.sl_at = swing_high_at, swing_low_at
        self.highs, self.lows = [], []   # 新しい順
        self.keep = keep
        self.pos = 0

    def advance_to(self, bar):
        while self.pos <= bar:
            if self.sh_at[self.pos] is not None:
                self.highs.insert(0, self.sh_at[self.pos])
                self.highs = self.highs[:self.keep]
            if self.sl_at[self.pos] is not None:
                self.lows.insert(0, self.sl_at[self.pos])
                self.lows = self.lows[:self.keep]
            self.pos += 1

    def dow_trend(self):
        if len(self.highs) < 2 or len(self.lows) < 2:
            return 0
        hh = self.highs[0][0] > self.highs[1][0]
        hl = self.lows[0][0] > self.lows[1][0]
        lh = self.highs[0][0] < self.highs[1][0]
        ll = self.lows[0][0] < self.lows[1][0]
        if hh and hl: return 1
        if lh and ll: return -1
        return 0


# ============================================================
# 4P-Score バックテスト
# ============================================================
def backtest_4pscore(df_1h):
    df_4h = resample(df_1h, '4h')
    df_d1 = resample(df_1h, '1D')
    df_1h = add_atr(df_1h.copy())
    df_4h = add_atr(df_4h)
    df_1h['MA20'] = df_1h['Close'].rolling(20).mean()
    df_4h['MA20'] = df_4h['Close'].rolling(20).mean()

    h1_h, h1_l = df_1h['High'].values, df_1h['Low'].values
    sh1, sl1 = find_swings(h1_h, h1_l)
    sh4, sl4 = find_swings(df_4h['High'].values, df_4h['Low'].values)
    shd, sld = find_swings(df_d1['High'].values, df_d1['Low'].values)

    tr1 = SwingTracker(sh1, sl1)
    tr4 = SwingTracker(sh4, sl4)
    trd = SwingTracker(shd, sld)

    # 1Hバー → 4H/D1バーのマッピング
    idx4 = df_4h.index.searchsorted(df_1h.index, side='right') - 1
    idxd = df_d1.index.searchsorted(df_1h.index, side='right') - 1
    ma4_arr = df_4h['MA20'].values
    atr4_arr = df_4h['ATR'].values

    closes = df_1h['Close'].values
    ma1_arr = df_1h['MA20'].values
    atr1_arr = df_1h['ATR'].values

    trades = []
    in_trade = False
    sl = tp = direction = 0

    for i in range(100, len(df_1h)):
        c = closes[i]

        # 決済判定
        if in_trade:
            if direction == 1:
                if c <= sl:
                    trades.append({'pnl_r': -1.0, 'date': df_1h.index[i]}); in_trade = False
                elif c >= tp:
                    trades.append({'pnl_r': RISK_REWARD, 'date': df_1h.index[i]}); in_trade = False
            else:
                if c >= sl:
                    trades.append({'pnl_r': -1.0, 'date': df_1h.index[i]}); in_trade = False
                elif c <= tp:
                    trades.append({'pnl_r': RISK_REWARD, 'date': df_1h.index[i]}); in_trade = False
        if in_trade:
            continue

        # スイングトラッカーを現在バーまで進める
        tr1.advance_to(i)
        if idx4[i] >= 0: tr4.advance_to(idx4[i])
        if idxd[i] >= 0: trd.advance_to(idxd[i])

        # --- 大きな流れ: 4Hダウ理論 ---
        big = tr4.dow_trend()
        if big == 0:
            continue
        d = big  # トレンドフォローのみ

        # --- 執行足(1H)の転換イベント ---
        if len(tr1.highs) < 2 or len(tr1.lows) < 2:
            continue
        if d == -1:
            lower_high = tr1.highs[0][0] < tr1.highs[1][0]
            seq_ok = tr1.lows[0][1] < tr1.highs[0][1]   # 安値→戻り高値の順
            level = tr1.lows[0][0]
            fresh = closes[i-1] >= level and c < level
            swing_extreme = tr1.highs[0][0]
            if not (lower_high and seq_ok and fresh):
                continue
        else:
            higher_low = tr1.lows[0][0] > tr1.lows[1][0]
            seq_ok = tr1.highs[0][1] < tr1.lows[0][1]
            level = tr1.highs[0][0]
            fresh = closes[i-1] <= level and c > level
            swing_extreme = tr1.lows[0][0]
            if not (higher_low and seq_ok and fresh):
                continue

        # ===== スコアリング =====
        score = 40

        # 要素①: 日足合致（逆行=戦争状態なら却下）
        day = trd.dow_trend()
        if day == d:
            score += 20
        elif day == 0:
            score += 5
        else:
            continue

        # 要素②: 反対勢力（4H・D1スイング）までの距離
        atr_big = atr4_arr[idx4[i]] if idx4[i] >= 0 else np.nan
        if np.isnan(atr_big) or atr_big <= 0:
            continue
        opp_levels = []
        for swings, side in [(tr4.lows if d == -1 else tr4.highs, 'big'),
                             (trd.lows if d == -1 else trd.highs, 'day')]:
            for price, _ in swings:
                if (d == -1 and price < c) or (d == 1 and price > c):
                    opp_levels.append(price)
        if opp_levels:
            nearest = max(opp_levels) if d == -1 else min(opp_levels)
            dist_atr = abs(c - nearest) / atr_big
            if dist_atr < OPP_VETO_ATR:
                continue  # 反対勢力が近すぎ → 却下
            elif dist_atr >= OPP_FULL_ATR:
                score += 20
            elif dist_atr >= (OPP_VETO_ATR + OPP_FULL_ATR) / 2:
                score += 10
            else:
                score += 5
        else:
            score += 20  # 視界良好

        # MA整列
        ma1 = ma1_arr[i]
        ma4 = ma4_arr[idx4[i]] if idx4[i] >= 0 else np.nan
        ma4_prev = ma4_arr[idx4[i]-4] if idx4[i] >= 4 else np.nan
        if not (np.isnan(ma1) or np.isnan(ma4) or np.isnan(ma4_prev)):
            if d == -1 and c < ma1 < ma4 and ma4 < ma4_prev:
                score += 10
            elif d == 1 and c > ma1 > ma4 and ma4 > ma4_prev:
                score += 10

        # リトレース深さ（30〜70%が理想）
        if d == -1 and len(tr1.highs) >= 2:
            wave = tr1.highs[1][0] - tr1.lows[0][0]
            retr = tr1.highs[0][0] - tr1.lows[0][0]
        elif d == 1 and len(tr1.lows) >= 2:
            wave = tr1.highs[0][0] - tr1.lows[1][0]
            retr = tr1.highs[0][0] - tr1.lows[0][0]
        else:
            wave = retr = 0
        if wave > 0:
            ratio = retr / wave
            if 0.30 <= ratio <= 0.70:
                score += 10
            elif 0.70 < ratio <= 0.85:
                score += 5

        if score < MIN_SCORE:
            continue

        # ===== エントリー（SL=直近スイングの向こう側） =====
        atr1 = atr1_arr[i]
        if np.isnan(atr1) or atr1 <= 0:
            continue
        if d == -1:
            sl = swing_extreme + atr1 * SL_BUFFER_ATR
            sl_dist = sl - c
            if sl_dist < atr1: sl_dist = atr1 * 2.0; sl = c + sl_dist
            tp = c - sl_dist * RISK_REWARD
        else:
            sl = swing_extreme - atr1 * SL_BUFFER_ATR
            sl_dist = c - sl
            if sl_dist < atr1: sl_dist = atr1 * 2.0; sl = c - sl_dist
            tp = c + sl_dist * RISK_REWARD
        direction = d
        in_trade = True

    return trades


# ============================================================
# ベースライン: MAスロープ版（FX4Pattern_EA 相当）
# ============================================================
def backtest_baseline(df_1h):
    df_4h = resample(df_1h, '4h')
    df_1h = add_atr(df_1h.copy())
    df_1h['MA20'] = df_1h['Close'].rolling(20).mean()
    df_4h['MA20'] = df_4h['Close'].rolling(20).mean()

    def trend(ma):
        slope = ma.diff(MA_SLOPE_WINDOW)
        return np.where(slope > 0, 1, np.where(slope < 0, -1, 0))

    df_4h['trend_4h'] = trend(df_4h['MA20'])
    df_1h = df_1h.join(df_4h[['trend_4h']].reindex(df_1h.index, method='ffill'))
    df_1h['trend_1h'] = trend(df_1h['MA20'])
    df_1h['prev_trend_1h'] = df_1h['trend_1h'].shift(1)

    df_1h['buy'] = (df_1h['trend_4h'] == 1) & (df_1h['trend_1h'] == 1) & (df_1h['prev_trend_1h'] == -1)
    df_1h['sell'] = (df_1h['trend_4h'] == -1) & (df_1h['trend_1h'] == -1) & (df_1h['prev_trend_1h'] == 1)

    trades, in_trade = [], False
    sl = tp = direction = 0
    data = df_1h.dropna(subset=['MA20', 'ATR', 'trend_4h'])

    for i in range(len(data)):
        row = data.iloc[i]
        c, atr = row['Close'], row['ATR']
        if in_trade:
            if direction == 1:
                if c <= sl: trades.append({'pnl_r': -1.0, 'date': data.index[i]}); in_trade = False
                elif c >= tp: trades.append({'pnl_r': RISK_REWARD, 'date': data.index[i]}); in_trade = False
            else:
                if c >= sl: trades.append({'pnl_r': -1.0, 'date': data.index[i]}); in_trade = False
                elif c <= tp: trades.append({'pnl_r': RISK_REWARD, 'date': data.index[i]}); in_trade = False
        if not in_trade and atr > 0:
            if row['buy']:
                sl = c - atr * 2.0; tp = c + atr * 2.0 * RISK_REWARD
                direction = 1; in_trade = True
            elif row['sell']:
                sl = c + atr * 2.0; tp = c - atr * 2.0 * RISK_REWARD
                direction = -1; in_trade = True
    return trades


# ============================================================
# 集計
# ============================================================
def summarize(trades):
    if not trades:
        return None
    df = pd.DataFrame(trades)
    wins = df[df['pnl_r'] > 0]
    losses = df[df['pnl_r'] < 0]
    total_r = df['pnl_r'].sum()
    pf = wins['pnl_r'].sum() / losses['pnl_r'].abs().sum() if len(losses) else 999
    cumr = df['pnl_r'].cumsum()
    max_dd = (cumr - cumr.cummax()).min()
    return {
        'trades': len(df), 'win_rate': len(wins) / len(df) * 100,
        'total_r': total_r, 'pf': pf, 'max_dd': max_dd,
    }


# ============================================================
# メイン
# ============================================================
print("=" * 66)
print(" 4P-Score オリジナルシグナルシステム vs 従来MAスロープ版")
print(f" 期間: 合成{BACKTEST_YEARS}年  RR 1:{RISK_REWARD}  最低スコア: {MIN_SCORE}点(Aグレード)")
print("=" * 66)

totals = {'base': [], 'score': []}
for name, config in PAIR_CONFIG.items():
    n_hours = HOURS_PER_YEAR * BACKTEST_YEARS
    df_1h = generate_ohlc(config, n_hours)

    base = summarize(backtest_baseline(df_1h))
    orig = summarize(backtest_4pscore(df_1h))

    print(f"\n--- {name} " + "-" * 50)
    for label, r in [('従来版(MAスロープ)', base), ('4P-Score(ダウ理論+採点)', orig)]:
        if r is None:
            print(f"  {label:<24}: トレードなし")
            continue
        print(f"  {label:<24}: {r['trades']:>4}回  勝率{r['win_rate']:5.1f}%  "
              f"{r['total_r']:+7.1f}R  PF{r['pf']:5.2f}  最大DD{r['max_dd']:+6.1f}R")
    if base: totals['base'].append(base)
    if orig: totals['score'].append(orig)

print("\n" + "=" * 66)
print(" 【合計比較】")
print("=" * 66)
for key, label in [('base', '従来版(MAスロープ)'), ('score', '4P-Score(オリジナル)')]:
    rs = totals[key]
    if not rs: continue
    t = sum(r['trades'] for r in rs)
    w = sum(r['trades'] * r['win_rate'] / 100 for r in rs)
    r_sum = sum(r['total_r'] for r in rs)
    pf = (w * RISK_REWARD) / (t - w) if t > w else 999
    print(f"  {label:<24}: {t:>4}回  勝率{w/t*100:5.1f}%  {r_sum:+7.1f}R  PF{pf:5.2f}")

print()
print("【注意事項】")
print("  ・合成データによるシミュレーションです（実データではありません）")
print("  ・4P-Scoreはシグナルを厳選するためトレード数は減りますが、")
print("    1トレードあたりの期待値（勝率・PF）の向上を狙う設計です")
print("  ・実運用前に必ずMT5ストラテジーテスターで実データ検証してください")
print("=" * 66)
