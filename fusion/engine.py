"""
バー駆動のバックテストエンジン（MT5のEAが「新しい足」ごとに判定する流れを再現）

1本の基準足（M15 または H1）ごとに次の順で処理する:
  1. 前の足の終値で出た注文を、この足の始値で約定（成行）／逆指値は足の中で約定判定
  2. 建玉をこの足の高値・安値で処理（損切り・利確・部分利確）
  3. 足の確定時: 戦略の manage()（トレール・時間決済）→ 週末決済
  4. 足の確定時: 取引時間内なら戦略の on_bar_close() で新規シグナルを判定 → 次の足へ注文

戦略クラスは prepare(engine) / on_bar_close(ctx) / manage(ctx, pos) を実装する。
ctx.last[tf] は「この基準足の確定時点で確定済みの tf の最後の足インデックス」、
ctx.closed_now[tf] は「この基準足の確定と同時に tf の足が確定したか」。
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from fusion import broker as bk
from fusion import data as fd
from fusion import indicators as ind

ORDER = ['M15', 'H1', 'H4', 'D1']


@dataclass
class Order:
    direction: int
    sl: float
    tp: Optional[float] = None          # 絶対価格
    tp_r: Optional[float] = None        # 約定価格からのR倍数（tp より優先）
    tp1: Optional[float] = None
    tp1_r: Optional[float] = None
    tp1_frac: float = 0.0
    be_after_tp1: bool = False
    be_offset: float = 0.0
    entry: str = 'market'               # 'market'（次の足の始値）/ 'stop'（逆指値）
    stop_price: Optional[float] = None
    expiry_bars: int = 1                # 逆指値の有効本数（基準足）
    min_rr: Optional[float] = None      # 約定時点で再計算したRRがこれ未満なら約定させない（tp が絶対価格の場合）
    meta: dict = field(default_factory=dict)


class Context:
    def __init__(self, engine, i):
        self.engine = engine
        self.i = i
        self.time = engine.base.index[i]
        self.close_time = self.time + engine.base_delta
        self.last = {tf: int(engine.maps[tf][i]) for tf in engine.tfs}
        self.closed_now = {tf: bool(engine.closed_now[tf][i]) for tf in engine.tfs}
        self.broker = engine.broker

    @property
    def open_positions(self):
        return self.engine.broker.open

    def close(self, pos, reason):
        self.engine.broker.close(pos, self.close_time, self.engine.C[self.i], reason)


class Engine:
    def __init__(self, frames, strategy, spread=0.0, base_tf=None, trade_hours=(0, 24),
                 friday_no_entry_hour=20, friday_close_hour=22, max_positions=1, warmup=0):
        """frames: {'M15': df, 'H1': df, ...}（足りない上位足は基準足から作る）"""
        self.base_tf = base_tf or next(tf for tf in ORDER if tf in frames)
        base = frames[self.base_tf]
        self.frames = dict(frames)
        for tf in ORDER[ORDER.index(self.base_tf) + 1:]:
            if tf not in self.frames:
                self.frames[tf] = fd.resample(base, tf)
        self.tfs = ORDER[ORDER.index(self.base_tf):]
        self.base = base
        self.base_delta = fd.TF_DELTA[self.base_tf]
        self.O, self.H, self.L, self.C = (base[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
        self.maps, self.closed_now = {}, {}
        for tf in self.tfs:
            f = self.frames[tf]
            m = ind.closed_index_map(base.index, self.base_delta, f.index, fd.TF_DELTA[tf])
            self.maps[tf] = m
            self.closed_now[tf] = np.r_[m[0] >= 0, m[1:] != m[:-1]]
        self.strategy = strategy
        self.broker = bk.Broker(spread)
        self.spread = spread
        self.trade_hours = trade_hours
        self.friday_no_entry_hour = friday_no_entry_hour
        self.friday_close_hour = friday_close_hour
        self.max_positions = max_positions
        self.warmup = warmup
        self.pending = []           # (Order, 残り有効本数)
        self.rejected = 0

    # ---- 時間のルール（サーバー時間） ----
    def entry_allowed(self, close_time):
        h = close_time.hour + close_time.minute / 60
        a, b = self.trade_hours
        if not (a <= h < b):
            return False
        if close_time.dayofweek == 4 and h >= self.friday_no_entry_hour:
            return False
        return True

    def weekend_due(self, close_time):
        return close_time.dayofweek == 4 and close_time.hour >= self.friday_close_hour or close_time.dayofweek >= 5

    # ---- 約定 ----
    def _fill(self, order, i, price):
        d = order.direction
        entry = price + d * self.spread / 2
        risk = (entry - order.sl) * d
        if risk <= 0:
            self.rejected += 1
            return None
        tp = entry + d * order.tp_r * risk if order.tp_r is not None else order.tp
        tp1 = entry + d * order.tp1_r * risk if order.tp1_r is not None else order.tp1
        if order.min_rr is not None and tp is not None and (tp - entry) * d / risk < order.min_rr:
            self.rejected += 1
            return None
        pos = self.broker.open_position(self.base.index[i], price, d, order.sl, tp=tp, tp1=tp1,
                                        tp1_frac=order.tp1_frac, be_after_tp1=order.be_after_tp1,
                                        be_offset=order.be_offset, meta=order.meta)
        return pos

    def run(self):
        st = self.strategy
        st.prepare(self)
        n = len(self.base)
        for i in range(self.warmup, n):
            t = self.base.index[i]
            o, h, l, c = self.O[i], self.H[i], self.L[i], self.C[i]
            # 1) 注文の約定
            still = []
            for order, left in self.pending:
                if len(self.broker.open) >= self.max_positions:
                    continue
                if order.entry == 'market':
                    pos = self._fill(order, i, o)
                    if pos is not None:
                        self.broker.process_bar(pos, t, o, h, l, c)
                    continue
                # 逆指値: 買いは Ask 高値、売りは Bid 安値が届いたら約定（窓開けは始値）
                d, sp = order.direction, order.stop_price
                ask_h, bid_l = h + self.spread / 2, l - self.spread / 2
                o_side = o + d * self.spread / 2
                touched = (ask_h >= sp) if d == 1 else (bid_l <= sp)
                if touched:
                    fill_mid = (max(o_side, sp) if d == 1 else min(o_side, sp)) - d * self.spread / 2
                    pos = self._fill(order, i, fill_mid)
                    if pos is not None:
                        self.broker.process_bar(pos, t, o, h, l, c, entry_bar=True)
                elif left > 1:
                    still.append((order, left - 1))
            self.pending = still
            # 2) 既存建玉の処理（この足で約定したものは処理済み）
            for pos in list(self.broker.open):
                if pos.entry_time != t:
                    self.broker.process_bar(pos, t, o, h, l, c)
            # 3) 足の確定時の管理
            ctx = Context(self, i)
            for pos in list(self.broker.open):
                st.manage(ctx, pos)
            if self.weekend_due(ctx.close_time):
                for pos in list(self.broker.open):
                    ctx.close(pos, 'WEEKEND')
                self.pending = []
                continue
            # 4) 新規シグナル
            if len(self.broker.open) >= self.max_positions or not self.entry_allowed(ctx.close_time):
                continue
            orders = st.on_bar_close(ctx) or []
            for od in orders:
                self.pending.append((od, od.expiry_bars))
        # 最終足で残った建玉は終値で決済
        if n:
            last_t = self.base.index[-1] + self.base_delta
            for pos in list(self.broker.open):
                self.broker.close(pos, last_t, self.C[-1], 'END')
        return [bk.trade_record(p) for p in sorted(self.broker.closed, key=lambda p: p.id)]
