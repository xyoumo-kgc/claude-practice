"""
FUSION-CORE ダッシュボード（賢人のデイトレード × 100億円トレーダー 融合システム）

  streamlit run dashboard/fusion_app.py

- 実データ（MT5 で書き出した H1 足の CSV）を読み込み、最後の確定足での判定・チャート・過去の成績を表示する
- 判定は fusion/strategy.py（MT5 EA と同じルールの Python 参照実装）をそのまま使う
- 合成データは使わない（合成データでは成績が実態と大きくずれることが分かったため）
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fusion import data as fd  # noqa: E402
from fusion import indicators as ind  # noqa: E402
from fusion import stats as fst  # noqa: E402
from fusion import strategy as fs  # noqa: E402

st.set_page_config(page_title='FUSION-CORE ダッシュボード', layout='wide', page_icon='📈')

REASON = {
    'R00': '指標の準備中',
    'R01': '4時間足の構造（G1）が不成立',
    'R02': '押しが 4H MA（SMA80）に届いていない',
    'R03': '押しの中に 1H の戻り高値がない',
    'R04': '1H の安値切上げが崩れた',
    'R05': '消化済み（戻り高値を終値で更新済み）',
    'R06': '約定済みのセットアップ',
    'R07': '遅すぎ（G3）',
    'R08': '4H MA が逆向き',
    'R09': '損切り幅 R が小さすぎる',
    'R10': '損切り幅 R が大きすぎる',
    'R11': '日足と逆行',
    'R12': '4H MA と日足 MA が乖離',
    'R13': '1H 転換型ではない',
    'R14': '背後に節目の支えがない',
    'R15': '前方の反対勢力が近い',
    'R16': '目標の節目が近い',
}
STATE_JA = {
    'IDLE': '待機（4H構造なし）', 'WATCH': '監視（押し待ち）', 'ZONE': 'ゾーン（1H転換待ち）',
    'ARMED': '逆指値を設置', 'FILLED': '保有中', 'PAUSED': '停止中（週末・休場・ロールオーバー）',
}
DIR_JA = {1: '買い', -1: '売り'}
VARIANT_JA = {
    'fusion': 'fusion（既定）',
    'oku_only': '100億の要素だけ（oku_only）',
    'kenjin_only': '賢人の要素だけ（kenjin_only）',
    'mincore_final': '設計時の選択版（mincore_final）',
}


# ------------------------------------------------------------------ データ
@st.cache_data(show_spinner=False)
def load_sample():
    return fd.load_backtesting_eurusd()


@st.cache_data(show_spinner=False)
def load_upload(raw: bytes, name: str):
    with tempfile.NamedTemporaryFile('wb', suffix=os.path.splitext(name)[1] or '.csv', delete=False) as f:
        f.write(raw)
        path = f.name
    try:
        return fd.load_mt5_csv(path)
    finally:
        os.unlink(path)


@st.cache_data(show_spinner=False)
def analyse(h1: pd.DataFrame, sym: str, variant: str):
    snap = fs.snapshot(h1, sym, fs.config(variant))
    return snap


def grade(score):
    """SPEC §9 のグレード（情報用）"""
    return 'S' if score >= 80 else 'A' if score >= 65 else 'B' if score >= 50 else 'C'


def guess_symbol(name):
    up = (name or '').upper()
    for s in fs.S_NOM:
        if s in up:
            return s
    return 'EURUSD'


# ------------------------------------------------------------------ サイドバー
st.sidebar.title('⚙️ 設定')
sources = ['MT5 の H1 足 CSV をアップロード']
try:
    fd.backtesting_eurusd_path()
    sources.insert(0, 'サンプル: EURUSD 1時間足（2017-04〜2018-02）')
except FileNotFoundError:
    pass
src = st.sidebar.radio('データ', sources)
h1, sym_default = None, 'EURUSD'
if src.startswith('サンプル'):
    h1 = load_sample()
else:
    up = st.sidebar.file_uploader('MT5「チャートバー」の書き出し（H1）', type=['csv', 'txt'])
    st.sidebar.caption('MT5: 表示 → 銘柄 → チャートバー → H1 を選んで「バーを要求」→「書き出し」。1万本以上あると全機能が働きます。')
    if up is not None:
        h1 = load_upload(up.getvalue(), up.name)
        sym_default = guess_symbol(up.name)
syms = list(fs.S_NOM)
sym = st.sidebar.selectbox('銘柄（スプレッドと暦に使う）', syms, index=syms.index(sym_default))
offset = st.sidebar.number_input('サーバー時間のずれ（時間）', value=0, step=1,
                                 help='ブローカーのサーバー時間 −（NY時間＋7時間）。多くの MT5 ブローカーは 0。')
variant = st.sidebar.selectbox('構成', list(VARIANT_JA), format_func=VARIANT_JA.get)
st.sidebar.markdown('---')
st.sidebar.markdown(
    '**FUSION-CORE とは**  \n'
    '4時間足の押し目・戻り目（1時間足の SMA80 付近）で、1時間足が「安値切上げ＋戻り高値の上抜け」に転じる瞬間を逆指値で取る。'
    '損切りは切上げ安値の外、出口は4Hレベルの構造トレールと週末決済だけ。')

st.title('📈 FUSION-CORE ダッシュボード')
st.caption('賢人のデイトレード × 100億円トレーダー — 両者に共通する中核セットアップを機械化したシステム')

if h1 is None or h1.empty:
    st.info('サイドバーでデータを選んでください。')
    st.stop()
if fd.infer_tf(h1) != 'H1':
    st.error(f'H1 足のデータを読み込んでください（判定された時間足: {fd.infer_tf(h1)}）。')
    st.stop()

shift = pd.Timedelta(hours=int(offset))
h1_ny7 = h1.copy()
h1_ny7.index = h1_ny7.index - shift                      # 判定はサーバー時間＝NY+7 に換算して行う
with st.spinner('判定中...'):
    snap = analyse(h1_ny7, sym, variant)


def to_server(t):
    return None if t is None else pd.Timestamp(t) + shift


trades = pd.DataFrame(snap['trades'])
if not trades.empty:
    for c in ('entry_time', 'exit_time'):
        trades[c] = pd.to_datetime(trades[c]) + shift

tab1, tab2, tab3, tab4 = st.tabs(['🎯 いまの判定', '🕯️ チャート', '📊 過去の成績', '📖 仕組みと注意'])

# ------------------------------------------------------------------ TAB1: いまの判定
with tab1:
    last_t = to_server(snap['time'])
    st.subheader(f'{sym}　最後の確定足: {last_t:%Y-%m-%d %H:%M}（サーバー時間）')
    if len(h1) < 10000:
        st.warning(f'読み込んだ足は {len(h1):,} 本です。日足レベルの情報（日足との関係・節目の一部）を正しく出すには 1万本以上が必要です。'
                   '売買の判定そのものは 3,100 本程度あれば動きます。')
    pos, pend = snap['position'], snap['pending']
    if snap['paused']:
        st.info(f"⏸ 停止中: {snap['paused']}（新規の判定をしない時間帯です）")
    if pos:
        r_now = pos['r_now']
        st.success(f"🟢 保有中: {DIR_JA[pos['direction']]}　約定 {pos['entry']:.5f}（{to_server(pos['entry_time']):%m-%d %H:%M}）　"
                   f"現在の損切り {pos['sl']:.5f}　含み {r_now:+.2f}R")
    if pend:
        m = pend['meta']
        st.warning(f"🟠 逆指値を設置中: {DIR_JA[pend['dir']]}　価格 {pend['price']:.5f}　損切り {pend['sl']:.5f}　"
                   f"R={m['r_atr']:.2f}ATR　TP1目安 {pend['tp1']:.5f}　スコア {m['score']}（{grade(m['score'])}）")
    cols = st.columns(2)
    for col, d in zip(cols, (1, -1)):
        e = snap['evals'].get(d) or {}
        state = e.get('state') or ('FILLED' if pos else ('PAUSED' if snap['paused'] else 'IDLE'))
        with col:
            st.markdown(f"### {DIR_JA[d]}: {STATE_JA.get(state, state)}")
            code = e.get('code')
            if code and code != 'OK':
                st.write(f"止まっている条件: **{code}** {REASON.get(code, '')}")
            diag = e.get('diag') or {}
            rows = []
            if 'j_peak_time' in diag:
                rows.append(('G1 4H構造', f"成立（押しの起点 {to_server(diag['j_peak_time']):%m-%d %H:%M}）"))
            elif code in ('R01',):
                rows.append(('G1 4H構造', '不成立'))
            if 'depth' in diag:
                rows.append(('G2 押しの深さ', f"{diag['depth']:+.2f} ATR（0.5 以下で到達）"))
            if 'slope' in diag:
                rows.append(('4H MA の傾き', f"{diag['slope']:+.3f}（0 以上で OK）"))
            if 'sh' in diag:
                rows.append(('1H 戻り高値' if d == 1 else '1H 押し安値', f"{diag['sh']:.5f}"))
            if 'run_ext' in diag:
                rows.append(('切上げ安値' if d == 1 else '切下げ高値', f"{diag['run_ext']:.5f}（直前 {diag['l0']:.5f}）"))
            if 'price' in diag:
                rows.append(('逆指値', f"{diag['price']:.5f}"))
                rows.append(('損切り', f"{diag['sl']:.5f}（R={diag['r_atr']:.2f}ATR）"))
            if 'score' in diag:
                rows.append(('スコア', f"{diag['score']}（S1 {diag['s1']} / S2 {diag['s2']} / S3 {diag['s3']} / "
                                     f"S4 {diag['s4']} / S5 {diag['s5']} / S6 {diag['s6']}）"))
                rows.append(('日足との関係', {1: '合致', 0: '中立', -1: '逆行'}[diag['rel']]))
                rows.append(('背後の支え', diag['sup'] or 'なし'))
                rows.append(('前方の反対勢力', '見当たらない' if diag['rr_cf'] >= 99 else f"{diag['rr_cf']:.1f}R 先"))
            if rows:
                st.table(pd.DataFrame(rows, columns=['項目', '値']).set_index('項目'))
    st.caption('状態: IDLE（4H構造なし）→ WATCH（押し待ち）→ ZONE（1H転換待ち）→ ARMED（逆指値）→ FILLED（保有）。'
               'スコアは情報用で、売買の条件には使っていません。')

# ------------------------------------------------------------------ TAB2: チャート
with tab2:
    n_show = st.slider('表示する本数', 150, 1500, 400, 50)
    view = h1.iloc[-n_show:]
    C = h1['Close'].to_numpy(float)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=view.index, open=view['Open'], high=view['High'], low=view['Low'], close=view['Close'],
                                 name='H1', increasing_line_color='#26a69a', decreasing_line_color='#ef5350'))
    for n, color in ((20, '#1e88e5'), (80, '#e53935'), (480, '#fbc02d')):
        fig.add_trace(go.Scatter(x=view.index, y=ind.sma(C, n)[-n_show:], name=f'SMA{n}', line=dict(width=1.4, color=color)))
    H, L = h1['High'].to_numpy(float), h1['Low'].to_numpy(float)
    book = ind.SwingBook(H, L, 12, lookback=3000)
    last = len(h1) - 1
    first_view = len(h1) - n_show
    hs = [(p, j) for p, j in book.highs(last, 40) if j >= first_view]
    ls = [(p, j) for p, j in book.lows(last, 40) if j >= first_view]
    fig.add_trace(go.Scatter(x=[h1.index[j] for _, j in hs], y=[p for p, _ in hs], mode='markers', name='4Hレベルの高値',
                             marker=dict(symbol='triangle-down', size=9, color='#8e24aa')))
    fig.add_trace(go.Scatter(x=[h1.index[j] for _, j in ls], y=[p for p, _ in ls], mode='markers', name='4Hレベルの安値',
                             marker=dict(symbol='triangle-up', size=9, color='#8e24aa')))
    lo_v, hi_v = view['Low'].min(), view['High'].max()
    for lv in sorted(snap['levels'], key=lambda x: -x['touch'])[:8]:
        if lo_v <= lv['price'] <= hi_v and (lv['touch'] >= 2 or lv['d1']):
            fig.add_hline(y=lv['price'], line=dict(color='#757575', width=1 + min(lv['touch'], 5) * 0.6, dash='dot'),
                          annotation_text=f"節目 x{lv['touch']}{' 日足' if lv['d1'] else ''}", annotation_position='top left')
    if pend:
        fig.add_hline(y=pend['price'], line=dict(color='#fb8c00', width=2), annotation_text='逆指値')
        fig.add_hline(y=pend['sl'], line=dict(color='#e53935', width=2, dash='dash'), annotation_text='損切り')
    if pos:
        fig.add_hline(y=pos['entry'], line=dict(color='#43a047', width=2), annotation_text='建値')
        fig.add_hline(y=pos['sl'], line=dict(color='#e53935', width=2, dash='dash'), annotation_text='損切り（トレール後）')
    if not trades.empty:
        tv = trades[trades['entry_time'] >= view.index[0]]
        fig.add_trace(go.Scatter(x=tv['entry_time'], y=tv['entry'], mode='markers', name='エントリー',
                                 marker=dict(symbol=np.where(tv['direction'] > 0, 'triangle-up', 'triangle-down'),
                                             size=12, color=np.where(tv['direction'] > 0, '#2e7d32', '#c62828'),
                                             line=dict(width=1, color='black'))))
    fig.update_layout(height=640, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10),
                      legend=dict(orientation='h', y=1.04))
    fig.update_xaxes(rangebreaks=[dict(bounds=['sat', 'mon'])])
    st.plotly_chart(fig, width='stretch')
    st.caption('青 SMA20（1時間足）・赤 SMA80（＝4時間足の20MA）・黄 SMA480（＝日足の20MA）。紫の三角は 4時間足レベルの高値・安値（左右12本）。'
               '点線は節目（太いほど反応回数が多い）。')

# ------------------------------------------------------------------ TAB3: 過去の成績
with tab3:
    st.info('この表は、読み込んだデータでの機械的な検証結果です。将来の成績を保証しません。'
            '事前登録した未接触データ（7銘柄・約15年）での最終検証では、優位性を確認できませんでした'
            '（不合格。平均 +0.055R/回、t=1.07。詳細は fusion/RESULTS.md）。')
    done = trades[trades['exit_reason'] != 'END'] if not trades.empty else trades
    s = fst.summarize(done.to_dict('records'), sym)
    if not s or not s.get('trades'):
        st.write('取引はまだありません。')
    else:
        k = st.columns(6)
        k[0].metric('取引数', s['trades'])
        k[1].metric('勝率', f"{s['win_rate'] * 100:.1f}%")
        k[2].metric('総損益', f"{s['total_r']:+.1f}R")
        k[3].metric('平均', f"{s['avg_r']:+.3f}R")
        k[4].metric('PF', f"{s['pf']:.2f}")
        k[5].metric('最大DD', f"{s['max_dd_r']:.1f}R")
        eq = done.sort_values('exit_time')
        fig2 = go.Figure(go.Scatter(x=eq['exit_time'], y=eq['pnl_r'].cumsum(), mode='lines', line=dict(color='#1e88e5')))
        fig2.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), yaxis_title='累積R')
        st.plotly_chart(fig2, width='stretch')
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('**年別**')
            y = done.groupby(done['entry_time'].dt.year)['pnl_r'].agg(['count', 'sum', 'mean'])
            y.columns = ['回数', '総R', '平均R']
            y.index.name = '年'
            st.dataframe(y.style.format({'総R': '{:+.1f}', '平均R': '{:+.3f}'}), width='stretch')
        with c2:
            st.markdown('**決済の理由**')
            e = done.groupby('exit_reason')['pnl_r'].agg(['count', 'sum', 'mean'])
            e.columns = ['回数', '総R', '平均R']
            e.index.name = '理由'
            st.dataframe(e.style.format({'総R': '{:+.1f}', '平均R': '{:+.3f}'}), width='stretch')
        show = done[['entry_time', 'direction', 'entry', 'initial_sl', 'exit_time', 'exit_reason', 'pnl_r', 'm_score']].copy()
        show['direction'] = show['direction'].map(DIR_JA)
        show.columns = ['エントリー', '方向', '約定', '初期損切り', '決済', '理由', 'R', 'スコア']
        st.dataframe(show.sort_values('エントリー', ascending=False), width='stretch', height=360)

# ------------------------------------------------------------------ TAB4: 仕組みと注意
with tab4:
    st.markdown("""
#### 判定の流れ（すべて確定した1時間足で判定し、次の足から注文が有効）
| 段階 | 条件 | 由来 |
|---|---|---|
| G1 4時間足の構造 | 4Hレベル（左右12本）の高値・安値がともに切上げ、終値が直近の押し安値より上（売りは逆） | 両者共通（ダウ理論） |
| G2 押しの場所 | 押しの間に、安値が SMA80（＝4時間足の20MA）から 0.5ATR 以内まで来た | 両者共通（4H MA への押し） |
| MA の向き | SMA80 が 12本前より下がっていない | 両者共通（MA は向きで読む） |
| 1H の転換 | 1H の戻り高値の後、安値切上げを保ったまま、その高値の少し上に逆指値 | 両者共通（中核セットアップ） |
| 損切り | 切上げ安値の外（0.2ATR、最低でもスプレッドの3倍） | 両者共通（根拠が崩れる位置） |
| 出口 | 4Hレベルの新しい押し安値ができるたびに損切りを引き上げる＋金曜22時（休場前）に全決済 | 賢人の構造トレール＋100億の週末ルール |

日足との関係・背後の節目・前方の反対勢力は **表示とスコアだけ** で、売買は止めません（事前登録した検証でそれぞれの効果を測っています）。

#### 注意
- **事前登録した最終検証で不合格でした。** 未接触の7銘柄・約15年（1,609回）で平均 +0.055R/回（t=1.07）。
  ゼロとも、トレンド方向にでたらめに入る素朴なやり方とも区別できませんでした（`fusion/RESULTS.md`）。
  売買の自動化には使わず、相場を同じ規則で読むための補助として使ってください。
- 勝率は 25〜30% 前後、損益の中央値は −1R。利益は週末まで持った少数の取引に集中し、10〜20連敗は想定内です。
- 裁量で分割決済・建値移動・早めの利確を加えると、別の戦略になります（期待値が大きく変わります）。
- 投資助言ではありません。自動売買を使う場合も、デモ口座での確認から始めてください。

詳しくは `fusion/SPEC.md`（仕様）、`fusion/THEORY.md`（賢人と100億円トレーダーの共通点の検証）、`mt5/README_FUSION.md`（MT5 EA）を参照してください。
""")
