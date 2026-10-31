"""
融合システム用の特徴量（すべて確定済みデータだけから計算する）

- 節目（水平線）: 上位足の確定スイングを価格の近さでまとめ、反応回数・役割転換（レジサポ転換）を数える
- MA乖離: (短期MA - 長期MA) / ATR。収束（小さい）→拡散（広がる）の判定に使う
- リスクリワード: 損切りまでの距離と、利確目標（次の節目）までの距離の比
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Level:
    price: float
    touches: int
    highs: int                      # スイング高値として反応した回数
    lows: int                       # スイング安値として反応した回数
    last_idx: int                   # 最後に反応したスイングの足インデックス
    members: list = field(default_factory=list)

    @property
    def role_reversal(self):
        """高値としても安値としても機能した＝レジサポ転換ライン"""
        return self.highs > 0 and self.lows > 0


def cluster_levels(swings, tol):
    """swings: [(price, idx, kind)]（kind=+1 高値 / -1 安値）。
    価格順に並べ、隣との差が tol 以下のものを同じ節目にまとめる（単連結）。"""
    if not swings:
        return []
    pts = sorted(swings, key=lambda s: s[0])
    groups, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[0] - cur[-1][0] <= tol:
            cur.append(p)
        else:
            groups.append(cur)
            cur = [p]
    groups.append(cur)
    out = []
    for g in groups:
        prices = [x[0] for x in g]
        out.append(Level(
            price=float(np.median(prices)),
            touches=len(g),
            highs=sum(1 for x in g if x[2] > 0),
            lows=sum(1 for x in g if x[2] < 0),
            last_idx=max(x[1] for x in g),
            members=g,
        ))
    return out


def swings_for_levels(book, last_closed, lookback_bars, max_each=40):
    """SwingBook から、last_closed 時点で確定済みかつ直近 lookback_bars 本以内のスイングを集める"""
    lo = last_closed - lookback_bars + 1
    hs = [(p, j, 1) for p, j in book.highs(last_closed, max_each) if j >= lo]
    ls = [(p, j, -1) for p, j in book.lows(last_closed, max_each) if j >= lo]
    return hs + ls


def next_level(levels, price, direction, min_touches=1, min_dist=0.0):
    """direction=+1: price より上で最も近い節目 / -1: 下で最も近い節目（min_dist 以上離れたもの）"""
    best = None
    for lv in levels:
        if lv.touches < min_touches:
            continue
        d = (lv.price - price) * direction
        if d > min_dist and (best is None or d < (best.price - price) * direction):
            best = lv
    return best


def support_near(levels, price, direction, tol, min_touches=1):
    """押し目買い（direction=+1）なら price の近く（tol 以内）〜下にある支持の節目、
    戻り売り（-1）なら近く〜上にある抵抗の節目のうち、最も近いもの"""
    best, best_d = None, None
    for lv in levels:
        if lv.touches < min_touches:
            continue
        d = (price - lv.price) * direction   # 買い: 価格が節目より上にある距離
        if -tol <= d <= tol and (best is None or abs(d) < best_d):
            best, best_d = lv, abs(d)
    return best


def ma_gap(fast, slow, atr_arr):
    """(短期MA - 長期MA) / ATR"""
    with np.errstate(invalid='ignore', divide='ignore'):
        return (np.asarray(fast) - np.asarray(slow)) / np.asarray(atr_arr)


def converge_then_diverge(gap, i, direction, conv_thr, div_thr, window):
    """足 i 時点で: 直近 window 本のどこかで |gap| <= conv_thr（収束）があり、
    いま gap*direction >= div_thr かつ前の足より広がっている（拡散）"""
    if i < window or np.isnan(gap[i]) or np.isnan(gap[i - 1]):
        return False
    past = gap[i - window:i]
    if np.all(np.isnan(past)) or np.nanmin(np.abs(past)) > conv_thr:
        return False
    return gap[i] * direction >= div_thr and gap[i] * direction > gap[i - 1] * direction


def risk_reward(entry, stop, target, direction):
    risk = (entry - stop) * direction
    reward = (target - entry) * direction
    if risk <= 0:
        return float('nan')
    return reward / risk
