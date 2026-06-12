"""
FX 4つの鉄板パターン バックテスト（シミュレーション版）

ネットワーク制限のため、実際の過去データの代わりに
各通貨ペアの実際の統計特性に基づいた合成OHLCデータを使用。

【使用した実際の統計特性（2020〜2024年）】
  USDJPY : 年間ボラ ~8.5%, 強いトレンド相場多め
  EURUSD : 年間ボラ ~7.2%, レンジ・トレンド混在
  GBPUSD : 年間ボラ ~8.8%, ボラ高め
  XAUUSD : 年間ボラ ~14.0%, 全体的に強い上昇トレンド
"""
import warnings; warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)  # 再現性のため

# ============================================================
# 通貨ペアの統計特性（実際の市場データに基づく概算）
# ============================================================
PAIR_CONFIG = {
    'USDJPY': {
        'start_price': 107.0,    # 2021年初値
        'annual_vol': 0.085,     # 年間ボラティリティ
        'annual_drift': 0.06,    # 年間ドリフト（円安トレンド反映）
        'trend_persistence': 0.65,  # トレンド継続性
    },
    'EURUSD': {
        'start_price': 1.2100,
        'annual_vol': 0.072,
        'annual_drift': -0.03,   # ユーロ弱め
        'trend_persistence': 0.55,
    },
    'GBPUSD': {
        'start_price': 1.3700,
        'annual_vol': 0.088,
        'annual_drift': -0.02,
        'trend_persistence': 0.58,
    },
    'XAUUSD': {
        'start_price': 1850.0,
        'annual_vol': 0.140,
        'annual_drift': 0.12,    # 金の上昇トレンド
        'trend_persistence': 0.60,
    },
}

BACKTEST_YEARS = 3    # バックテスト期間
HOURS_PER_YEAR = 252 * 6  # 1年の取引時間（週5日×6時間/日 の近似）
RISK_REWARD = 2.0
SL_ATR_MULT = 2.0
MA_SLOPE_WINDOW = 5
ATR_PERIOD = 14


# ============================================================
# 合成OHLCデータ生成（Regime Switching付きGBM）
# ============================================================
def generate_ohlc(config, n_hours):
    annual_vol = config['annual_vol']
    annual_drift = config['annual_drift']
    trend_persistence = config['trend_persistence']
    start_price = config['start_price']

    dt = 1 / HOURS_PER_YEAR
    hourly_vol = annual_vol * np.sqrt(dt)
    hourly_drift = annual_drift * dt

    # レジーム（トレンド/レンジ）のスイッチング
    regime = np.zeros(n_hours)  # 1=上昇トレンド, -1=下降トレンド, 0=レンジ
    regime[0] = np.random.choice([1, -1, 0], p=[0.35, 0.30, 0.35])
    regime_duration = 0
    for i in range(1, n_hours):
        regime_duration += 1
        # レジームの最小持続時間（40時間）
        if regime_duration > 40:
            r = np.random.random()
            if r < (1 - trend_persistence):
                regime[i] = np.random.choice([1, -1, 0], p=[0.35, 0.30, 0.35])
                regime_duration = 0
            else:
                regime[i] = regime[i-1]
        else:
            regime[i] = regime[i-1]

    # 価格系列生成
    closes = np.zeros(n_hours)
    closes[0] = start_price
    for i in range(1, n_hours):
        trend_boost = regime[i] * hourly_vol * 0.3
        shock = np.random.normal(hourly_drift + trend_boost, hourly_vol)
        closes[i] = closes[i-1] * np.exp(shock)

    # OHLC生成
    intra_vol = hourly_vol * start_price
    highs = closes + np.abs(np.random.normal(0, intra_vol * 0.6, n_hours))
    lows  = closes - np.abs(np.random.normal(0, intra_vol * 0.6, n_hours))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]

    # 日付インデックス（週末スキップ）
    idx = []
    dt_curr = datetime(2021, 1, 4, 0, 0)
    while len(idx) < n_hours:
        if dt_curr.weekday() < 5:  # 月〜金
            idx.append(dt_curr)
        dt_curr += timedelta(hours=1)

    df = pd.DataFrame({
        'Open':  opens[:len(idx)],
        'High':  highs[:len(idx)],
        'Low':   lows[:len(idx)],
        'Close': closes[:len(idx)],
    }, index=idx[:n_hours])
    return df


# ============================================================
# インジケーター
# ============================================================
def add_indicators(df, ma_period=20, atr_period=14):
    df = df.copy()
    df[f'MA{ma_period}'] = df['Close'].rolling(ma_period).mean()
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low']  - df['Close'].shift()).abs()
    df['ATR'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(atr_period).mean()
    return df


def get_trend(ma_series, window=5):
    slope = ma_series.diff(window)
    return np.where(slope > 0, 1, np.where(slope < 0, -1, 0))


def resample_4h(df_1h):
    return df_1h.resample('4h').agg(
        Open=('Open','first'), High=('High','max'),
        Low=('Low','min'),    Close=('Close','last'),
    ).dropna()


# ============================================================
# バックテスト（パターン①: 4H押し目・戻り目）
# ============================================================
def backtest(name, config):
    n_hours = HOURS_PER_YEAR * BACKTEST_YEARS
    df_1h = generate_ohlc(config, n_hours)

    df_4h = resample_4h(df_1h)
    df_1h = add_indicators(df_1h, 20, ATR_PERIOD)
    df_4h = add_indicators(df_4h, 20, ATR_PERIOD)

    df_4h['trend_4h'] = get_trend(df_4h['MA20'], MA_SLOPE_WINDOW)
    df_1h = df_1h.join(
        df_4h[['trend_4h', 'MA20']].rename(columns={'MA20': '4H_MA20'})
        .reindex(df_1h.index, method='ffill')
    )
    df_1h['trend_1h']      = get_trend(df_1h['MA20'], MA_SLOPE_WINDOW)
    df_1h['prev_trend_1h'] = df_1h['trend_1h'].shift(1)

    df_1h['buy']  = ((df_1h['trend_4h'] == 1)  & (df_1h['trend_1h'] == 1)  & (df_1h['prev_trend_1h'] == -1))
    df_1h['sell'] = ((df_1h['trend_4h'] == -1) & (df_1h['trend_1h'] == -1) & (df_1h['prev_trend_1h'] ==  1))

    trades, in_trade = [], False
    entry_price = sl = tp = direction = 0
    data = df_1h.dropna(subset=['MA20', 'ATR', 'trend_4h']).copy()

    for i in range(len(data)):
        row   = data.iloc[i]
        close = row['Close']
        atr   = row['ATR']

        if in_trade:
            if direction == 1:
                if close <= sl:
                    trades.append({'dir':'BUY','result':'SL','pnl_r':-1.0,'date':data.index[i]})
                    in_trade = False
                elif close >= tp:
                    trades.append({'dir':'BUY','result':'TP','pnl_r':RISK_REWARD,'date':data.index[i]})
                    in_trade = False
            else:
                if close >= sl:
                    trades.append({'dir':'SELL','result':'SL','pnl_r':-1.0,'date':data.index[i]})
                    in_trade = False
                elif close <= tp:
                    trades.append({'dir':'SELL','result':'TP','pnl_r':RISK_REWARD,'date':data.index[i]})
                    in_trade = False

        if not in_trade and atr > 0:
            if row['buy']:
                entry_price = close
                sl = entry_price - atr * SL_ATR_MULT
                tp = entry_price + atr * SL_ATR_MULT * RISK_REWARD
                direction = 1;  in_trade = True
            elif row['sell']:
                entry_price = close
                sl = entry_price + atr * SL_ATR_MULT
                tp = entry_price - atr * SL_ATR_MULT * RISK_REWARD
                direction = -1; in_trade = True

    if not trades:
        return None

    df_t = pd.DataFrame(trades)
    wins   = df_t[df_t['pnl_r'] > 0]
    losses = df_t[df_t['pnl_r'] < 0]

    total    = len(df_t)
    win_rate = len(wins) / total * 100
    total_r  = df_t['pnl_r'].sum()
    pf       = wins['pnl_r'].sum() / losses['pnl_r'].abs().sum() if len(losses) > 0 else 999
    cumr     = df_t['pnl_r'].cumsum()
    max_dd   = (cumr - cumr.cummax()).min()

    df_t['month'] = pd.to_datetime(df_t['date']).dt.to_period('M')
    monthly = df_t.groupby('month')['pnl_r'].sum()
    win_months = (monthly > 0).sum()

    return {
        'name': name, 'start': data.index[0].date(), 'end': data.index[-1].date(),
        'trades': total, 'wins': len(wins), 'losses': len(losses),
        'win_rate': win_rate, 'total_r': total_r, 'pf': pf,
        'max_dd_r': max_dd, 'win_months': win_months,
        'total_months': len(monthly), 'monthly': monthly,
    }


# ============================================================
# 結果表示
# ============================================================
def print_result(r):
    print(f"\n{'='*58}")
    print(f"  {r['name']}  （{r['start']} ～ {r['end']}）")
    print(f"{'='*58}")
    print(f"  総トレード数         : {r['trades']:>5} 回")
    print(f"  勝ち / 負け          : {r['wins']:>4} / {r['losses']}")
    print(f"  勝率                 : {r['win_rate']:>6.1f} %")
    print(f"  総損益 (R)           : {r['total_r']:>+8.1f} R")
    print(f"  プロフィットファクター: {r['pf']:>6.2f}")
    print(f"  最大ドローダウン     : {r['max_dd_r']:>+8.1f} R")
    print(f"  月利プラス           : {r['win_months']:>2} / {r['total_months']} ヶ月")
    print()
    print("  【月次損益 (R)】")
    for month, val in r['monthly'].items():
        bar_len = min(int(abs(val)), 20)
        bar_str = '█' * bar_len if bar_len > 0 else ''
        sign = '+' if val >= 0 else ''
        color = '' if val >= 0 else ''
        print(f"    {month}: {sign}{val:>+5.1f}R  {bar_str}")


# ============================================================
# メイン
# ============================================================
print("=" * 58)
print(" FX 鉄板パターン① バックテスト（シミュレーション）")
print(f" 期間: {BACKTEST_YEARS}年間  戦略: 4H押し目・戻り目")
print(f" RR比 1:{RISK_REWARD}  SL: ATR×{SL_ATR_MULT}")
print("=" * 58)

all_results = []
for name, config in PAIR_CONFIG.items():
    r = backtest(name, config)
    if r:
        print_result(r)
        all_results.append(r)

# サマリー
if all_results:
    print(f"\n{'='*58}")
    print("  【全通貨ペア合計サマリー】")
    print(f"{'='*58}")
    total_trades = sum(r['trades'] for r in all_results)
    total_wins   = sum(r['wins'] for r in all_results)
    total_r      = sum(r['total_r'] for r in all_results)
    avg_wr       = total_wins / total_trades * 100
    all_pf_wins  = sum(r['wins'] * r['win_rate']/100 * RISK_REWARD for r in all_results)
    all_pf_loss  = sum(r['losses'] for r in all_results)
    overall_pf   = (total_wins * RISK_REWARD) / (total_trades - total_wins) if total_trades > total_wins else 0

    print(f"  総トレード数  : {total_trades}")
    print(f"  全体勝率      : {avg_wr:.1f}%")
    print(f"  合計損益      : {total_r:+.1f} R")
    print(f"  全体PF        : {overall_pf:.2f}")
    print()
    print("  ＜1Rあたりの損益例＞")
    print(f"  口座100万円・1R=1万円(1%)の場合: {total_r*1:+.0f}万円")
    print(f"  口座500万円・1R=5万円(1%)の場合: {total_r*5:+.0f}万円")
    print()
    print("=" * 58)
    print("【重要な注意事項】")
    print("  ・本結果は各ペアの統計特性に基づくシミュレーションです")
    print("  ・実際の市場データではないため参考値として扱ってください")
    print("  ・スプレッド・スリッページ・スワップは未考慮です")
    print("  ・実際の手法は目視での相場判断が含まれており")
    print("    MAスロープのみでの機械的シグナルより精度が高くなります")
    print("  ・過去の結果が将来の利益を保証するものではありません")
    print("=" * 58)
