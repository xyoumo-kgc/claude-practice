"""
インジケーター・スイング検出・時間足の対応づけ（MQL5版と同じ定義）

先読み防止の約束:
  - スイングは「左右 depth 本」が確定して初めて認識する（認識＝スイング足＋depth 本目の確定時）
  - 上位足は「実行足の確定時刻までに確定した足」だけを参照する（closed_index_map）
"""
from bisect import bisect_right

import numpy as np
import pandas as pd


def sma(close, n):
    """MT5 iMA(MODE_SMA, PRICE_CLOSE) と同じ単純移動平均"""
    return pd.Series(close).rolling(n).mean().to_numpy()


def atr(high, low, close, n=14):
    """MT5 iATR と同じ定義: TR = max(H, 前C) - min(L, 前C) の単純平均（先頭足のTRは使わない）"""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    return pd.Series(tr).rolling(n).mean().to_numpy()


def pivots(high, low, depth):
    """スイング（フラクタル）判定。MQL5 FindSwingHighs/Lows と同じ不等号:
       高値: 新しい側 depth 本より厳密に高く、古い側 depth 本以上
       安値: 新しい側 depth 本より厳密に低く、古い側 depth 本以下
    戻り値: (is_high, is_low) の bool 配列。バー j のスイングはバー j+depth の確定時に認識される。"""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    n = len(h)
    is_h = np.zeros(n, dtype=bool)
    is_l = np.zeros(n, dtype=bool)
    if n < 2 * depth + 1:
        return is_h, is_l
    is_h[depth:n - depth] = True
    is_l[depth:n - depth] = True
    for k in range(1, depth + 1):
        mid = slice(depth, n - depth)
        newer = slice(depth + k, n - depth + k)
        older = slice(depth - k, n - depth - k)
        is_h[mid] &= (h[mid] > h[newer]) & (h[mid] >= h[older])
        is_l[mid] &= (l[mid] < l[newer]) & (l[mid] <= l[older])
    return is_h, is_l


class SwingBook:
    """ある時間足の確定済みスイングを、任意の確定足インデックス時点で取り出す。

    latest(last_closed, k) は MQL5 の FindSwingHighs/Lows（lookback 本以内・新しい順）と同じ集合を返す:
      スイング足インデックス j が  last_closed - lookback + 2 <= j <= last_closed - depth  のもの。
    """

    def __init__(self, high, low, depth, lookback=400, times=None):
        self.depth = depth
        self.lookback = lookback
        self.high = np.asarray(high, dtype=float)
        self.low = np.asarray(low, dtype=float)
        self.times = times
        ih, il = pivots(self.high, self.low, depth)
        self.h_idx = np.flatnonzero(ih)
        self.l_idx = np.flatnonzero(il)

    def _latest(self, idx_arr, prices, last_closed, k):
        if last_closed is None or last_closed < 0:
            return []
        hi = last_closed - self.depth
        lo = max(last_closed - self.lookback + 2, self.depth + 1)  # MQL5 と同じく履歴先頭の depth+1 本は対象外
        end = bisect_right(idx_arr, hi)
        out = []
        p = end - 1
        while p >= 0 and len(out) < k:
            j = int(idx_arr[p])
            if j < lo:
                break
            out.append((float(prices[j]), j))
            p -= 1
        return out

    def highs(self, last_closed, k=4):
        """[(価格, 足インデックス), ...] 新しい順"""
        return self._latest(self.h_idx, self.high, last_closed, k)

    def lows(self, last_closed, k=4):
        return self._latest(self.l_idx, self.low, last_closed, k)

    def dow_trend(self, last_closed):
        """+1: 高値・安値とも切り上げ / -1: 両方切り下げ / 0: それ以外（MQL5 DowTrend と同じ）"""
        hs = self.highs(last_closed, 2)
        ls = self.lows(last_closed, 2)
        if len(hs) < 2 or len(ls) < 2:
            return 0
        hh, lh = hs[0][0] > hs[1][0], hs[0][0] < hs[1][0]
        hl, ll = ls[0][0] > ls[1][0], ls[0][0] < ls[1][0]
        if hh and hl:
            return 1
        if lh and ll:
            return -1
        return 0


def closed_index_map(exec_index, exec_delta, htf_index, htf_delta):
    """各実行足（開始 t、確定 t+exec_delta）の時点で確定済みの上位足の最後のインデックス（無ければ -1）。
    上位足の確定時刻 = 開始 + htf_delta。確定時刻 <= 実行足の確定時刻 のものだけを見る。"""
    t_close = (pd.DatetimeIndex(exec_index) + exec_delta).values
    h_close = (pd.DatetimeIndex(htf_index) + htf_delta).values
    return np.searchsorted(h_close, t_close, side='right') - 1
