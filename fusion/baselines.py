"""
比較用ベースライン（先読みを除いた再実装）

旧 fx_signal_backtest.py は、1時間足の判定で「まだ確定していない4時間足・日足」を参照していた
（searchsorted で足の開始時刻だけを比較していたため）。ここでは確定済みの上位足だけを使い、
損切り・利確は足の高値・安値で判定する。

  ma_slope   : 従来版EA（FX4Pattern_EA）相当。MA20 の傾きで 4H/1H のトレンドを近似
  fourp_score: 4P-Score（FX4Pattern_Signal）のパターン①（4H→1H）
"""
import numpy as np

from fusion import broker as bk
from fusion import data as fd
from fusion import indicators as ind

RR = 2.0


def _prep(h1):
    mtf = fd.build_mtf(h1, 'H1', ('H4', 'D1'))
    h4, d1 = mtf['H4'], mtf['D1']
    m4 = ind.closed_index_map(h1.index, fd.TF_DELTA['H1'], h4.index, fd.TF_DELTA['H4'])
    md = ind.closed_index_map(h1.index, fd.TF_DELTA['H1'], d1.index, fd.TF_DELTA['D1'])
    return h4, d1, m4, md


def _manage_exit(b, pos, t, o, h, l, c):
    b.process_bar(pos, t, o, h, l, c)


def ma_slope(h1, spread=0.0, slope_win=5):
    h4, _, m4, _ = _prep(h1)
    O, H, L, C = (h1[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
    ma1 = ind.sma(C, 20)
    atr1 = ind.atr(H, L, C, 14)
    ma4 = ind.sma(h4['Close'].to_numpy(), 20)
    tr1 = np.sign(ma1 - np.r_[[np.nan] * slope_win, ma1[:-slope_win]])
    tr4 = np.sign(ma4 - np.r_[[np.nan] * slope_win, ma4[:-slope_win]])
    b = bk.Broker(spread)
    pending = None
    for i in range(1, len(h1)):
        t = h1.index[i]
        if pending is not None and not b.open:
            d, sl_dist = pending
            mid = O[i]
            b.open_position(t, mid, d, sl=mid - d * sl_dist, tp=mid + d * sl_dist * RR)
        pending = None
        for pos in list(b.open):
            b.process_bar(pos, t, O[i], H[i], L[i], C[i])
        j = m4[i]
        if b.open or j < 0 or np.isnan(tr4[j]) or np.isnan(tr1[i]) or np.isnan(tr1[i - 1]) or np.isnan(atr1[i]):
            continue
        if tr4[j] == 1 and tr1[i] == 1 and tr1[i - 1] == -1:
            pending = (1, atr1[i] * 2.0)
        elif tr4[j] == -1 and tr1[i] == -1 and tr1[i - 1] == 1:
            pending = (-1, atr1[i] * 2.0)
    return [bk.trade_record(p) for p in b.closed]


def fourp_score(h1, spread=0.0, min_score=70, depth=3, opp_veto=1.0, opp_full=3.0, sl_buf=0.3):
    h4, d1, m4, md = _prep(h1)
    O, H, L, C = (h1[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
    atr1 = ind.atr(H, L, C, 14)
    ma1 = ind.sma(C, 20)
    atr4 = ind.atr(h4['High'], h4['Low'], h4['Close'], 14)
    ma4 = ind.sma(h4['Close'].to_numpy(), 20)
    b1 = ind.SwingBook(H, L, depth)
    b4 = ind.SwingBook(h4['High'], h4['Low'], depth)
    bd = ind.SwingBook(d1['High'], d1['Low'], depth)
    b = bk.Broker(spread)
    pending = None
    for i in range(2, len(h1)):
        t = h1.index[i]
        if pending is not None and not b.open:
            d, sl_level, score = pending
            mid = O[i]
            dist = (mid - sl_level) * d
            if dist > 0:
                b.open_position(t, mid, d, sl=sl_level, tp=mid + d * dist * RR, meta={'score': score})
        pending = None
        for pos in list(b.open):
            b.process_bar(pos, t, O[i], H[i], L[i], C[i])
        if b.open:
            continue
        j4, jd = m4[i], md[i]
        if j4 < 20:
            continue
        d = b4.dow_trend(j4)
        if d == 0:
            continue
        hs, ls = b1.highs(i, 2), b1.lows(i, 2)
        if len(hs) < 2 or len(ls) < 2:
            continue
        c, c_prev = C[i], C[i - 1]
        if d == -1:
            ok = hs[0][0] < hs[1][0] and ls[0][1] < hs[0][1] and c_prev >= ls[0][0] and c < ls[0][0]
            extreme = hs[0][0]
        else:
            ok = ls[0][0] > ls[1][0] and hs[0][1] < ls[0][1] and c_prev <= hs[0][0] and c > hs[0][0]
            extreme = ls[0][0]
        if not ok:
            continue
        score = 40
        day = bd.dow_trend(jd)
        if day == d:
            score += 20
        elif day == 0:
            score += 5
        else:
            continue
        a4 = atr4[j4]
        if not a4 or np.isnan(a4):
            continue
        opp = []
        for book, jj in ((b4, j4), (bd, jd)):
            sw = book.lows(jj, 4) if d == -1 else book.highs(jj, 4)
            opp += [p for p, _ in sw if (d == -1 and p < c) or (d == 1 and p > c)]
        if opp:
            nearest = max(opp) if d == -1 else min(opp)
            dist_atr = abs(c - nearest) / a4
            if dist_atr < opp_veto:
                continue
            score += 20 if dist_atr >= opp_full else (10 if dist_atr >= (opp_veto + opp_full) / 2 else 5)
        else:
            score += 20
        if j4 >= 4 and not np.isnan(ma1[i]) and not np.isnan(ma4[j4 - 4]):
            if d == -1 and c < ma1[i] < ma4[j4] and ma4[j4] < ma4[j4 - 4]:
                score += 10
            elif d == 1 and c > ma1[i] > ma4[j4] and ma4[j4] > ma4[j4 - 4]:
                score += 10
        if d == -1:
            wave, retr = hs[1][0] - ls[0][0], hs[0][0] - ls[0][0]
        else:
            wave, retr = hs[0][0] - ls[1][0], hs[0][0] - ls[0][0]
        if wave > 0:
            ratio = retr / wave
            score += 10 if 0.30 <= ratio <= 0.70 else (5 if 0.70 < ratio <= 0.85 else 0)
        if score < min_score or np.isnan(atr1[i]):
            continue
        sl_level = extreme - d * atr1[i] * sl_buf
        if (c - sl_level) * d < atr1[i]:
            sl_level = c - d * atr1[i] * 2.0
        pending = (d, sl_level, score)
    return [bk.trade_record(p) for p in b.closed]
