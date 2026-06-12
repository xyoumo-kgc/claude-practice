"""
4P-Score FX Dashboard
4つの鉄板パターン バックテスト・ダッシュボード
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# ─────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────
st.set_page_config(
    page_title="4P-Score FX Dashboard",
    layout="wide",
    page_icon="📈",
)

# ─────────────────────────────────────────
# 定数・設定
# ─────────────────────────────────────────
HOURS_PER_YEAR = 252 * 6

PAIR_CONFIG = {
    'USDJPY': {
        'start_price': 107.0,
        'annual_vol': 0.085,
        'annual_drift': 0.06,
        'trend_persistence': 0.65,
    },
    'EURUSD': {
        'start_price': 1.2100,
        'annual_vol': 0.072,
        'annual_drift': -0.03,
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
        'annual_drift': 0.12,
        'trend_persistence': 0.60,
    },
}

ALL_PAIRS = list(PAIR_CONFIG.keys())

# ─────────────────────────────────────────
# OHLC データ生成
# ─────────────────────────────────────────
def generate_ohlc(pair: str, years: int, seed: int = 42) -> pd.DataFrame:
    """幾何ブラウン運動 + レジームスイッチングで1H OHLCを生成する。"""
    cfg = PAIR_CONFIG[pair]
    start_price = cfg['start_price']
    annual_vol = cfg['annual_vol']
    annual_drift = cfg['annual_drift']
    trend_persistence = cfg['trend_persistence']

    hourly_vol = annual_vol / np.sqrt(HOURS_PER_YEAR)
    n_hours = int(years * HOURS_PER_YEAR)

    rng = np.random.default_rng(seed)

    # レジーム初期化 (1=上昇, -1=下降, 0=レンジ)
    regime = 1
    regime_duration = 0
    MIN_REGIME_BARS = 40

    prices = np.zeros(n_hours + 1)
    prices[0] = start_price
    regimes = np.zeros(n_hours, dtype=int)

    for i in range(n_hours):
        regimes[i] = regime
        regime_duration += 1

        # レジーム遷移
        if regime_duration >= MIN_REGIME_BARS:
            r = rng.random()
            if r < trend_persistence:
                pass  # 継続
            else:
                new_choices = [r2 for r2 in [1, -1, 0] if r2 != regime]
                regime = int(rng.choice(new_choices))
                regime_duration = 0

        drift = annual_drift / HOURS_PER_YEAR + regime * hourly_vol * 0.3
        shock = rng.standard_normal() * hourly_vol
        prices[i + 1] = prices[i] * np.exp(drift + shock)

    # OHLC 組み立て
    start_dt = datetime(2020, 1, 1)
    timestamps = [start_dt + timedelta(hours=i) for i in range(n_hours)]

    opens = prices[:n_hours]
    closes = prices[1:]

    high_noise = np.abs(rng.standard_normal(n_hours)) * hourly_vol * prices[:n_hours]
    low_noise = np.abs(rng.standard_normal(n_hours)) * hourly_vol * prices[:n_hours]

    highs = np.maximum(opens, closes) + high_noise
    lows = np.minimum(opens, closes) - low_noise

    df = pd.DataFrame({
        'datetime': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'regime': regimes,
    })
    df.set_index('datetime', inplace=True)
    return df


# ─────────────────────────────────────────
# ベースライン: MAスロープ順張り戦略
# ─────────────────────────────────────────
def run_baseline(df_1h: pd.DataFrame, rr: float) -> pd.DataFrame:
    """
    4H MAスロープ方向 + 1H MAスロープ反転でエントリー。
    リターンをR単位（1R = リスク固定）で記録。
    """
    # 4H リサンプル
    df_4h = df_1h['close'].resample('4h').last().dropna().to_frame('close')
    df_4h['ma20'] = df_4h['close'].rolling(20).mean()
    df_4h['slope'] = df_4h['ma20'].diff(3)
    # shift(1): バー i 時点では「直前に完了した4Hバー」のトレンドのみ既知（先読み防止）
    df_4h['trend'] = np.sign(df_4h['slope']).shift(1).fillna(0).astype(int)

    # 1H MA
    df_1h = df_1h.copy()
    df_1h['ma10'] = df_1h['close'].rolling(10).mean()
    df_1h['slope'] = df_1h['ma10'].diff(2)

    trades = []
    in_trade = False

    for i in range(30, len(df_1h)):
        row = df_1h.iloc[i]
        ts = df_1h.index[i]

        # 4H トレンド取得
        ts_4h = ts.floor('4h')
        if ts_4h not in df_4h.index:
            continue
        trend_4h = df_4h.loc[ts_4h, 'trend']

        if in_trade:
            in_trade = False
            continue

        prev_slope = df_1h['slope'].iloc[i - 1]
        curr_slope = df_1h['slope'].iloc[i]

        signal = 0
        if trend_4h == 1 and prev_slope < 0 and curr_slope > 0:
            signal = 1   # ロング
        elif trend_4h == -1 and prev_slope > 0 and curr_slope < 0:
            signal = -1  # ショート

        if signal != 0:
            entry = row['close']
            stop_dist = abs(row['close'] - df_1h['low'].iloc[i - 5:i].min()) if signal == 1 else \
                        abs(df_1h['high'].iloc[i - 5:i].max() - row['close'])
            if stop_dist < 1e-8:
                continue

            # 簡易シミュレーション: 次5本の値動きで判定
            future = df_1h.iloc[i + 1:i + 20]
            pnl = _simulate_trade(entry, stop_dist, rr, signal, future)
            trades.append({'datetime': ts, 'pnl_r': pnl, 'signal': signal})
            in_trade = True

    return pd.DataFrame(trades)


def _simulate_trade(entry, stop_dist, rr, signal, future_df):
    """簡易トレードシミュレーション。"""
    sl = entry - signal * stop_dist
    tp = entry + signal * stop_dist * rr

    for _, row in future_df.iterrows():
        if signal == 1:
            if row['low'] <= sl:
                return -1.0
            if row['high'] >= tp:
                return rr
        else:
            if row['high'] >= sl:
                return -1.0
            if row['low'] <= tp:
                return rr
    # 未決済: 終値で計算
    if len(future_df) > 0:
        last_close = future_df.iloc[-1]['close']
        raw = (last_close - entry) * signal / stop_dist
        return float(np.clip(raw, -1.0, rr))
    return 0.0


# ─────────────────────────────────────────
# 4P-Score: スイングベース ダウ理論逆張り
# ─────────────────────────────────────────
def detect_swings(df: pd.DataFrame, swing_depth: int = 3) -> pd.DataFrame:
    """スイング高値・安値を検出する。

    スイングはバー i の左右 swing_depth 本で判定するため、
    実際に「確定」するのは i + swing_depth 本目（confirm_idx）。
    バックテストでは confirm_idx 以降でのみ参照すること（先読み防止）。
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    swing_points = []
    for i in range(swing_depth, n - swing_depth):
        is_swing_high = all(highs[i] >= highs[i - j] for j in range(1, swing_depth + 1)) and \
                        all(highs[i] >= highs[i + j] for j in range(1, swing_depth + 1))
        is_swing_low = all(lows[i] <= lows[i - j] for j in range(1, swing_depth + 1)) and \
                       all(lows[i] <= lows[i + j] for j in range(1, swing_depth + 1))

        if is_swing_high:
            swing_points.append({'idx': i, 'confirm_idx': i + swing_depth,
                                 'datetime': df.index[i], 'type': 'H', 'price': highs[i]})
        elif is_swing_low:
            swing_points.append({'idx': i, 'confirm_idx': i + swing_depth,
                                 'datetime': df.index[i], 'type': 'L', 'price': lows[i]})

    return pd.DataFrame(swing_points) if swing_points else \
        pd.DataFrame(columns=['idx', 'confirm_idx', 'datetime', 'type', 'price'])


def calc_4p_score(swings: pd.DataFrame, idx: int, signal: int, df_1h: pd.DataFrame) -> int:
    """
    4P-Score スコア算出 (0-100点)。
    ベース40点 + ボーナス最大60点。

    ①ダウ理論的反転構造   +20
    ②モメンタム乖離       +15
    ③出来高/ボラ急変      +10 (近似: ボラ急増)
    ④-B ブレイクアウト    +15
    """
    score = 40  # ベーススコア

    # confirm_idx でフィルタ: idx 時点で確定済みのスイングのみ使用（先読み防止）
    recent_swings = swings[swings['confirm_idx'] <= idx].tail(6)
    if len(recent_swings) < 4:
        return score

    prices = recent_swings['price'].values
    types = recent_swings['type'].values

    # ① ダウ理論的反転構造
    if signal == 1:  # ロング: HH→HL→BRK
        lows_ = [p for p, t in zip(prices, types) if t == 'L']
        if len(lows_) >= 2 and lows_[-1] > lows_[-2]:
            score += 20
    else:  # ショート: LL→LH→BRK
        highs_ = [p for p, t in zip(prices, types) if t == 'H']
        if len(highs_) >= 2 and highs_[-1] < highs_[-2]:
            score += 20

    # ② モメンタム乖離 (簡易: 直近5本とその前の5本の変化量比較)
    if idx >= 10:
        mom_recent = abs(df_1h['close'].iloc[idx] - df_1h['close'].iloc[idx - 5])
        mom_prev = abs(df_1h['close'].iloc[idx - 5] - df_1h['close'].iloc[idx - 10])
        if mom_recent > mom_prev * 1.5:
            score += 15

    # ③ ボラ急増
    if idx >= 20:
        vol_recent = df_1h['close'].iloc[idx - 5:idx].std()
        vol_base = df_1h['close'].iloc[idx - 20:idx - 5].std()
        if vol_base > 0 and vol_recent > vol_base * 1.3:
            score += 10

    # ④-B ブレイクアウト確認
    if len(recent_swings) >= 2:
        last_swing_price = recent_swings.iloc[-1]['price']
        current_close = df_1h['close'].iloc[idx]
        if signal == 1 and current_close > last_swing_price:
            score += 15
        elif signal == -1 and current_close < last_swing_price:
            score += 15

    return min(score, 100)


def run_4p_score(df_1h: pd.DataFrame, rr: float, min_score: int, swing_depth: int) -> pd.DataFrame:
    """
    4P-Score バックテスト。
    スイング検出 → スコア算出 → min_score 以上のみエントリー。
    """
    swings = detect_swings(df_1h, swing_depth)
    if swings.empty:
        return pd.DataFrame()

    trades = []
    in_trade = False
    used_swing_idx = set()

    swing_highs = swings[swings['type'] == 'H']
    swing_lows = swings[swings['type'] == 'L']

    for i in range(50, len(df_1h) - 20):
        if in_trade:
            in_trade = False
            continue

        ts = df_1h.index[i]
        close = df_1h['close'].iloc[i]

        # 直近スイングから反転シグナル検出
        # confirm_idx <= i: バー i 時点で確定済みのスイングのみ参照（先読み防止）
        recent_swings = swings[swings['confirm_idx'] <= i].tail(4)
        if len(recent_swings) < 3:
            continue

        last = recent_swings.iloc[-1]

        signal = 0
        if last['type'] == 'L':
            # 安値圏からのロングシグナル候補
            prev_highs = swing_highs[swing_highs['idx'] < last['idx']].tail(2)
            if len(prev_highs) >= 1:
                resistance = prev_highs.iloc[-1]['price']
                if close > resistance * 0.999 and last['idx'] not in used_swing_idx:
                    signal = 1
                    used_swing_idx.add(last['idx'])

        elif last['type'] == 'H':
            # 高値圏からのショートシグナル候補
            prev_lows = swing_lows[swing_lows['idx'] < last['idx']].tail(2)
            if len(prev_lows) >= 1:
                support = prev_lows.iloc[-1]['price']
                if close < support * 1.001 and last['idx'] not in used_swing_idx:
                    signal = -1
                    used_swing_idx.add(last['idx'])

        if signal == 0:
            continue

        score = calc_4p_score(swings, i, signal, df_1h)
        if score < min_score:
            continue

        entry = close
        stop_dist = abs(close - last['price']) if signal == 1 else abs(last['price'] - close)
        if stop_dist < 1e-8:
            continue

        future = df_1h.iloc[i + 1:i + 30]
        pnl = _simulate_trade(entry, stop_dist, rr, signal, future)
        trades.append({
            'datetime': ts,
            'pnl_r': pnl,
            'signal': signal,
            'score': score,
        })
        in_trade = True

    return pd.DataFrame(trades)


# ─────────────────────────────────────────
# 統計計算
# ─────────────────────────────────────────
def calc_stats(trades: pd.DataFrame) -> dict:
    """トレード統計を計算する。"""
    if trades is None or len(trades) == 0:
        return {
            'n_trades': 0, 'win_rate': 0.0, 'total_r': 0.0,
            'pf': 0.0, 'max_dd': 0.0,
        }

    n = len(trades)
    wins = trades[trades['pnl_r'] > 0]
    losses = trades[trades['pnl_r'] < 0]
    win_rate = len(wins) / n if n > 0 else 0.0
    total_r = trades['pnl_r'].sum()
    gross_profit = wins['pnl_r'].sum()
    gross_loss = abs(losses['pnl_r'].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    equity = trades['pnl_r'].cumsum()
    # 初期資産 0 を含めてピークを取る（初回トレードから負け込んだ場合の DD を反映）
    rolling_max = equity.cummax().clip(lower=0.0)
    dd = equity - rolling_max
    max_dd = float(dd.min())

    return {
        'n_trades': n,
        'win_rate': win_rate,
        'total_r': total_r,
        'pf': pf,
        'max_dd': max_dd,
    }


def monthly_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """月次損益を集計する。"""
    if trades is None or len(trades) == 0:
        return pd.DataFrame(columns=['month', 'pnl_r'])
    t = trades.copy()
    t['month'] = pd.to_datetime(t['datetime']).dt.to_period('M').astype(str)
    return t.groupby('month')['pnl_r'].sum().reset_index()


# ─────────────────────────────────────────
# キャッシュ付きメインバックテスト実行
# ─────────────────────────────────────────
@st.cache_data(show_spinner=False)
def run_backtests(pairs: tuple, years: int, rr: float, min_score: int,
                  swing_depth: int, seed: int = 42) -> dict:
    """全ペアのバックテストを実行してキャッシュする。

    pairs はハッシュ可能な tuple で渡すこと。
    seed を含む全パラメータがキャッシュキーに入る。
    """
    results = {}
    for pair in pairs:
        df = generate_ohlc(pair, years, seed)
        bl_trades = run_baseline(df, rr)
        fp_trades = run_4p_score(df, rr, min_score, swing_depth)
        results[pair] = {
            'df': df,
            'baseline_trades': bl_trades,
            'fp_trades': fp_trades,
            'baseline_stats': calc_stats(bl_trades),
            'fp_stats': calc_stats(fp_trades),
        }
    return results


# ─────────────────────────────────────────
# UI ヘルパー
# ─────────────────────────────────────────
GOLD = '#FFD700'
GRAY_DASH = '#888888'

def fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"

def fmt_r(v: float) -> str:
    return f"{v:+.2f}R"

def fmt_pf(v: float) -> str:
    return f"{v:.2f}"


def color_delta(val: float, reference: float) -> str:
    """改善 / 悪化を示す delta 文字列を返す。"""
    diff = val - reference
    if abs(diff) < 0.01:
        return "±0"
    return f"{diff:+.2f}"


# ─────────────────────────────────────────
# サイドバー
# ─────────────────────────────────────────
st.sidebar.title("⚙️ パラメータ設定")

pair_options = ALL_PAIRS + ['全ペア']
selected_pair = st.sidebar.selectbox("通貨ペア", pair_options, index=0)

years = st.sidebar.slider("バックテスト期間（年）", min_value=1, max_value=5, value=3, step=1)
rr = st.sidebar.slider("RR比", min_value=1.0, max_value=3.0, value=2.0, step=0.5)
min_score = st.sidebar.slider("最低スコア（4P-Score）", min_value=55, max_value=90, value=70, step=5)
swing_depth = st.sidebar.slider("スイング深さ", min_value=2, max_value=5, value=3, step=1)

run_btn = st.sidebar.button("▶ バックテスト実行", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.markdown("""
**4P-Score とは**
4つの鉄板パターンに基づく
スコアリングシステムです。
最低スコアを上げるほど
エントリー数は減りますが
高品質なシグナルに絞れます。
""")

# ─────────────────────────────────────────
# メインエリア
# ─────────────────────────────────────────
st.title("📈 4P-Score FX Dashboard")
st.caption("4つの鉄板パターン — インタラクティブ・バックテスト")

# st.button は押した直後の 1 リランしか True にならないため、
# session_state に保持しないとタブ内の selectbox 操作等で画面が初期状態に戻ってしまう。
if run_btn:
    st.session_state['backtest_ran'] = True

if not st.session_state.get('backtest_ran', False):
    st.info("サイドバーでパラメータを設定し、**▶ バックテスト実行** を押してください。")
    st.stop()

# ── バックテスト実行 ──────────────────────
target_pairs = ALL_PAIRS if selected_pair == '全ペア' else [selected_pair]

with st.spinner("バックテスト実行中..."):
    results = run_backtests(tuple(target_pairs), years, rr, min_score, swing_depth, seed=42)

# ── 集計 ─────────────────────────────────
agg_bl = {'n_trades': 0, 'win_rate': 0.0, 'total_r': 0.0, 'pf': 0.0, 'max_dd': 0.0}
agg_fp = {'n_trades': 0, 'win_rate': 0.0, 'total_r': 0.0, 'pf': 0.0, 'max_dd': 0.0}

pf_data = []
for pair, res in results.items():
    bs = res['baseline_stats']
    fs = res['fp_stats']
    pf_data.append({'pair': pair, '従来版 PF': bs['pf'], '4P-Score PF': fs['pf']})
    for k in agg_bl:
        if k == 'max_dd':
            agg_bl[k] = min(agg_bl[k], bs[k])
            agg_fp[k] = min(agg_fp[k], fs[k])
        elif k == 'win_rate':
            pass
        else:
            agg_bl[k] += bs[k]
            agg_fp[k] += fs[k]

# 加重平均 勝率
n_bl = sum(r['baseline_stats']['n_trades'] for r in results.values())
n_fp = sum(r['fp_stats']['n_trades'] for r in results.values())
if n_bl > 0:
    agg_bl['win_rate'] = sum(
        r['baseline_stats']['win_rate'] * r['baseline_stats']['n_trades']
        for r in results.values()
    ) / n_bl
if n_fp > 0:
    agg_fp['win_rate'] = sum(
        r['fp_stats']['win_rate'] * r['fp_stats']['n_trades']
        for r in results.values()
    ) / n_fp

agg_bl['n_trades'] = n_bl
agg_fp['n_trades'] = n_fp

# 全ペア合算 PF
total_bl_profit = sum(
    r['baseline_trades']['pnl_r'].clip(lower=0).sum()
    for r in results.values()
    if len(r['baseline_trades']) > 0
)
total_bl_loss = sum(
    abs(r['baseline_trades']['pnl_r'].clip(upper=0).sum())
    for r in results.values()
    if len(r['baseline_trades']) > 0
)
total_fp_profit = sum(
    r['fp_trades']['pnl_r'].clip(lower=0).sum()
    for r in results.values()
    if len(r['fp_trades']) > 0
)
total_fp_loss = sum(
    abs(r['fp_trades']['pnl_r'].clip(upper=0).sum())
    for r in results.values()
    if len(r['fp_trades']) > 0
)
agg_bl['pf'] = total_bl_profit / total_bl_loss if total_bl_loss > 0 else 0.0
agg_fp['pf'] = total_fp_profit / total_fp_loss if total_fp_loss > 0 else 0.0

# ─────────────────────────────────────────
# タブ
# ─────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📊 概要", "📅 月次損益", "📈 エクイティカーブ", "🎯 スコア解説"])

# ════════════════════════════════════════
# TAB 1: 概要
# ════════════════════════════════════════
with tab1:
    st.subheader("パフォーマンス比較")

    col_bl, col_fp = st.columns(2)

    with col_bl:
        st.markdown("### 📉 従来版（MAスロープ）")
        m1, m2, m3 = st.columns(3)
        m1.metric("トレード数", agg_bl['n_trades'])
        m2.metric("勝率", fmt_pct(agg_bl['win_rate']))
        m3.metric("総損益", fmt_r(agg_bl['total_r']))
        m4, m5 = st.columns(2)
        m4.metric("プロフィットファクター", fmt_pf(agg_bl['pf']))
        m5.metric("最大DD", fmt_r(agg_bl['max_dd']))

    with col_fp:
        st.markdown(f"### 🥇 4P-Score（最低スコア: {min_score}）")
        m1, m2, m3 = st.columns(3)
        m1.metric(
            "トレード数", agg_fp['n_trades'],
            delta=color_delta(agg_fp['n_trades'], agg_bl['n_trades']),
        )
        m2.metric(
            "勝率", fmt_pct(agg_fp['win_rate']),
            delta=f"{(agg_fp['win_rate'] - agg_bl['win_rate']) * 100:+.1f}pp",
        )
        m3.metric(
            "総損益", fmt_r(agg_fp['total_r']),
            delta=color_delta(agg_fp['total_r'], agg_bl['total_r']),
        )
        m4, m5 = st.columns(2)
        m4.metric(
            "プロフィットファクター", fmt_pf(agg_fp['pf']),
            delta=color_delta(agg_fp['pf'], agg_bl['pf']),
        )
        m5.metric(
            "最大DD", fmt_r(agg_fp['max_dd']),
            delta=color_delta(agg_fp['max_dd'], agg_bl['max_dd']),
            delta_color="inverse",
        )

    st.markdown("---")

    # PF比較棒グラフ
    st.subheader("通貨ペア別 プロフィットファクター比較")

    if len(pf_data) > 0:
        pf_df = pd.DataFrame(pf_data)
        pf_melted = pf_df.melt(id_vars='pair', var_name='Strategy', value_name='PF')

        fig_pf = px.bar(
            pf_melted,
            x='pair',
            y='PF',
            color='Strategy',
            barmode='group',
            color_discrete_map={'従来版 PF': GRAY_DASH, '4P-Score PF': GOLD},
            labels={'pair': '通貨ペア', 'PF': 'プロフィットファクター', 'Strategy': '戦略'},
            title='',
        )
        fig_pf.add_hline(y=1.0, line_dash='dot', line_color='red', annotation_text='損益分岐点 (PF=1.0)')
        fig_pf.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation='h', y=-0.2),
            height=400,
        )
        st.plotly_chart(fig_pf, use_container_width=True)

# ════════════════════════════════════════
# TAB 2: 月次損益
# ════════════════════════════════════════
with tab2:
    st.subheader("月次損益（4P-Score）")

    if selected_pair == '全ペア':
        display_pair = st.selectbox("表示ペアを選択", ALL_PAIRS, key='monthly_pair')
    else:
        display_pair = selected_pair

    res = results[display_pair]
    fp_trades = res['fp_trades']
    bl_trades = res['baseline_trades']

    col_a, col_b = st.columns(2)

    for col, trades, label in [(col_a, bl_trades, '従来版'), (col_b, fp_trades, '4P-Score')]:
        with col:
            st.markdown(f"#### {label}")
            mdf = monthly_pnl(trades)

            if len(mdf) == 0:
                st.warning("トレードデータなし")
                continue

            pos_months = (mdf['pnl_r'] > 0).sum()
            st.caption(f"プラス月: {pos_months} / {len(mdf)} ヶ月")

            colors = ['#27AE60' if v >= 0 else '#FF4444' for v in mdf['pnl_r']]
            fig_m = go.Figure(go.Bar(
                x=mdf['month'],
                y=mdf['pnl_r'],
                marker_color=colors,
                hovertemplate='%{x}<br>損益: %{y:.2f}R<extra></extra>',
            ))
            fig_m.add_hline(y=0, line_color='white', line_width=1)
            fig_m.update_layout(
                xaxis_tickangle=-45,
                yaxis_title='損益 (R)',
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                height=380,
                showlegend=False,
            )
            st.plotly_chart(fig_m, use_container_width=True)

# ════════════════════════════════════════
# TAB 3: エクイティカーブ
# ════════════════════════════════════════
with tab3:
    st.subheader("エクイティカーブ")

    if selected_pair == '全ペア':
        eq_pair = st.selectbox("表示ペアを選択", ALL_PAIRS, key='equity_pair')
    else:
        eq_pair = selected_pair

    res = results[eq_pair]
    bl_t = res['baseline_trades']
    fp_t = res['fp_trades']

    fig_eq = go.Figure()

    for trades, name, color, dash in [
        (bl_t, '従来版', GRAY_DASH, 'dash'),
        (fp_t, '4P-Score', GOLD, 'solid'),
    ]:
        if len(trades) == 0:
            continue

        equity = trades['pnl_r'].cumsum()
        fig_eq.add_trace(go.Scatter(
            x=trades['datetime'],
            y=equity,
            mode='lines',
            name=name,
            line=dict(color=color, dash=dash, width=2),
            hovertemplate='%{x|%Y-%m-%d}<br>累積損益: %{y:.2f}R<extra>' + name + '</extra>',
        ))

        # 最大DD シェーディング（初期資産 0 をピークに含める）
        rolling_max = equity.cummax().clip(lower=0.0)
        dd_series = equity - rolling_max
        dd_start = None
        for j in range(len(dd_series)):
            if dd_series.iloc[j] < 0 and dd_start is None:
                dd_start = j
            elif dd_series.iloc[j] == 0 and dd_start is not None:
                x_range = list(trades['datetime'].iloc[dd_start:j + 1])
                y_top = list(rolling_max.iloc[dd_start:j + 1])
                y_bot = list(equity.iloc[dd_start:j + 1])
                if name == '4P-Score' and len(x_range) > 1:
                    fig_eq.add_trace(go.Scatter(
                        x=x_range + x_range[::-1],
                        y=y_top + y_bot[::-1],
                        fill='toself',
                        fillcolor='rgba(255,50,50,0.12)',
                        line=dict(width=0),
                        showlegend=False,
                        hoverinfo='skip',
                    ))
                dd_start = None

    fig_eq.add_hline(y=0, line_color='white', line_width=0.5, line_dash='dot')
    fig_eq.update_layout(
        xaxis_title='日時',
        yaxis_title='累積損益 (R)',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(orientation='h', y=-0.15),
        height=500,
        hovermode='x unified',
    )
    st.plotly_chart(fig_eq, use_container_width=True)

    # DD 統計
    col1, col2 = st.columns(2)
    for col, trades, label in [(col1, bl_t, '従来版'), (col2, fp_t, '4P-Score')]:
        with col:
            stats = calc_stats(trades)
            st.metric(f"{label} 最大DD", fmt_r(stats['max_dd']))

# ════════════════════════════════════════
# TAB 4: スコア解説
# ════════════════════════════════════════
with tab4:
    st.subheader("🎯 4P-Score スコアリングシステム解説")

    st.markdown("""
    4P-Score は **ダウ理論**に基づくスイング分析に、
    4つのパターン確認項目をスコアリングして
    エントリー品質を数値化するシステムです。
    """)

    st.markdown("---")

    # スコア内訳 (横積み棒グラフ)
    st.subheader("スコア内訳")

    categories = ['ベーススコア', '①ダウ反転構造', '②モメンタム乖離', '③ボラ急変', '④-B ブレイクアウト']
    values = [40, 20, 15, 10, 15]
    colors_score = ['#4A90D9', '#27AE60', '#E67E22', '#9B59B6', '#E74C3C']

    fig_score = go.Figure()
    cumulative = 0
    for cat, val, col_ in zip(categories, values, colors_score):
        fig_score.add_trace(go.Bar(
            name=cat,
            x=[val],
            y=['スコア構成'],
            orientation='h',
            marker_color=col_,
            text=f"{cat}<br>{val}pt",
            textposition='inside',
            hovertemplate=f"{cat}: {val}点<extra></extra>",
            base=cumulative,
        ))
        cumulative += val

    fig_score.update_layout(
        barmode='stack',
        xaxis=dict(range=[0, 105], title='点数'),
        height=120,
        showlegend=False,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=40),
    )
    st.plotly_chart(fig_score, use_container_width=True)

    st.markdown("---")

    # グレードバッジ
    st.subheader("グレード基準")

    col_s, col_a, col_b = st.columns(3)

    with col_s:
        st.markdown("""
        <div style="
            background: linear-gradient(135deg, #FFD700, #FFA500);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            color: #1a1a1a;
            font-weight: bold;
        ">
        <div style="font-size: 2.5rem;">🏆 S</div>
        <div style="font-size: 1.2rem;">85〜100点</div>
        <div style="font-size: 0.85rem; margin-top: 8px;">
        全条件が揃った<br>最高品質シグナル。<br>フルロットで入れる。
        </div>
        </div>
        """, unsafe_allow_html=True)

    with col_a:
        st.markdown("""
        <div style="
            background: linear-gradient(135deg, #C0C0C0, #A8A8A8);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            color: #1a1a1a;
            font-weight: bold;
        ">
        <div style="font-size: 2.5rem;">🥈 A</div>
        <div style="font-size: 1.2rem;">70〜84点</div>
        <div style="font-size: 0.85rem; margin-top: 8px;">
        高品質シグナル。<br>通常ロットで<br>積極的に狙う。
        </div>
        </div>
        """, unsafe_allow_html=True)

    with col_b:
        st.markdown("""
        <div style="
            background: linear-gradient(135deg, #CD7F32, #B8651A);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            color: #fff;
            font-weight: bold;
        ">
        <div style="font-size: 2.5rem;">🥉 B</div>
        <div style="font-size: 1.2rem;">55〜69点</div>
        <div style="font-size: 0.85rem; margin-top: 8px;">
        参考シグナル。<br>半ロット or<br>スキップも可。
        </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # パターン詳細
    st.subheader("4つの鉄板パターン詳細")

    patterns = [
        (
            "① ダウ理論的反転構造",
            "+20点",
            "#27AE60",
            """
**ロング条件**: 切り上げ安値（HL）形成後、直近高値をブレイク
**ショート条件**: 切り下げ高値（LH）形成後、直近安値をブレイク

ダウ理論の基本「高値・安値の更新で方向が決まる」を
スイング検出で自動判定します。
            """,
        ),
        (
            "② モメンタム乖離",
            "+15点",
            "#E67E22",
            """
直近5本の値動き幅が、その前の5本と比べて
**1.5倍以上**になっているかを確認。

エネルギーの集中を数値化することで、
偽ブレイクを排除します。
            """,
        ),
        (
            "③ ボラティリティ急変",
            "+10点",
            "#9B59B6",
            """
直近5本の価格標準偏差が、過去20本平均の
**1.3倍以上**になっているかを確認。

経済指標発表や重要イベントによる
急変動への乗り方を数値化します。
            """,
        ),
        (
            "④-B ブレイクアウト確認",
            "+15点",
            "#E74C3C",
            """
直近スイングポイントを**現在値が明確に超えているか**を確認。

「ブレイクしたように見えて戻る」フェイクアウトを
排除するための最終確認です。
            """,
        ),
    ]

    for name, pts, col_, desc in patterns:
        with st.expander(f"{name}　　**{pts}**"):
            st.markdown(desc)

    st.markdown("---")
    st.markdown("""
    > **使い方のヒント**
    > サイドバーの「最低スコア」を上げるとトレード数が減りますが、
    > 高品質なシグナルに絞り込めます。
    > RR比2.0 + 最低スコア70（グレードA以上）を基準として試してみてください。
    """)
