"""
約定シミュレーター（バーのOHLCだけで判定する保守的なモデル）

価格データは仲値（mid）とみなし、スプレッドは売買の両側に半分ずつ反映する:
  買い: 約定 = mid + s/2（Ask）、決済判定・約定は Bid = mid - s/2
  売り: 約定 = mid - s/2（Bid）、決済判定・約定は Ask = mid + s/2

1本の足の中の順序は分からないため、保守的に扱う:
  - 寄り付きが損切りを越えていれば寄り付き価格で損切り（窓開け）
  - 同じ足で損切りと利確の両方に届いたら損切りを優先
  - 部分利確の後に建値へ移した損切りも、同じ足の安値（高値）が届いていれば同じ足で約定させる
  - 逆指値エントリーが約定した足では、損切りの到達だけを判定し、利確は判定しない
損益はR（初期リスク = |約定価格 - 初期損切り|）で記録する。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    id: int
    direction: int                 # +1 買い / -1 売り
    entry_time: object
    entry_price: float             # スプレッド込みの約定価格
    sl: float                      # 現在の損切り
    initial_sl: float
    tp: Optional[float] = None     # 最終利確（None=トレールのみ）
    tp1: Optional[float] = None    # 部分利確
    tp1_frac: float = 0.0          # 部分利確で決済する割合
    be_after_tp1: bool = False     # 部分利確後に損切りを建値へ
    be_offset: float = 0.0         # 建値＋何価格単位に置くか（買いは上、売りは下）
    remaining: float = 1.0
    realized_r: float = 0.0
    tp1_done: bool = False
    exits: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    bars_held: int = 0
    mfe_r: float = 0.0
    mae_r: float = 0.0

    @property
    def risk(self):
        return abs(self.entry_price - self.initial_sl)


class Broker:
    def __init__(self, spread=0.0):
        self.spread = spread
        self.open = []
        self.closed = []
        self._next_id = 1

    # ---- 価格変換 ----
    def _fill_entry(self, mid, direction):
        return mid + direction * self.spread / 2

    def _exit_side(self, mid, direction):
        """決済側の価格（買い→Bid、売り→Ask）"""
        return mid - direction * self.spread / 2

    # ---- 建玉 ----
    def open_position(self, time, mid_price, direction, sl, tp=None, tp1=None, tp1_frac=0.0,
                      be_after_tp1=False, be_offset=0.0, meta=None):
        entry = self._fill_entry(mid_price, direction)
        if (entry - sl) * direction <= 0:
            return None  # 損切りが約定価格の反対側にない＝無効
        pos = Position(self._next_id, direction, time, entry, sl, sl, tp, tp1, tp1_frac,
                       be_after_tp1, be_offset, meta=dict(meta or {}))
        self._next_id += 1
        self.open.append(pos)
        return pos

    def _close_part(self, pos, time, price, frac, reason):
        frac = min(frac, pos.remaining)
        if frac <= 0:
            return
        r = frac * (price - pos.entry_price) * pos.direction / pos.risk
        pos.realized_r += r
        pos.remaining -= frac
        pos.exits.append((time, price, frac, reason))
        if pos.remaining <= 1e-9:
            pos.remaining = 0.0
            self.open.remove(pos)
            self.closed.append(pos)

    def close(self, pos, time, mid_price, reason):
        """足の終値などで残りを成行決済"""
        if pos in self.open:
            self._close_part(pos, time, self._exit_side(mid_price, pos.direction), pos.remaining, reason)

    def modify_sl(self, pos, new_sl):
        """損切りの変更（有利な方向にのみ）。次の足から有効。"""
        if (new_sl - pos.sl) * pos.direction > 0:
            # 現在値を越える損切りは置けない（呼び出し側で検証済みのこと）
            pos.sl = new_sl
            return True
        return False

    # ---- 1本の足の処理 ----
    def process_bar(self, pos, time, o, h, l, c, entry_bar=False):
        """建玉を1本の足（OHLC=mid）で処理する。entry_bar=True はその足の中で約定した逆指値。"""
        if pos not in self.open:
            return
        d = pos.direction
        s2 = self.spread / 2
        # 決済側の価格系列（買い→Bid、売り→Ask）
        o_x = o - d * s2
        fav = (h - s2) if d == 1 else (l + s2)     # 有利側の極値
        adv = (l - s2) if d == 1 else (h + s2)     # 不利側の極値

        # MFE/MAE（R）
        pos.mfe_r = max(pos.mfe_r, (fav - pos.entry_price) * d / pos.risk)
        pos.mae_r = min(pos.mae_r, (adv - pos.entry_price) * d / pos.risk)

        def hit_sl(level):
            return (adv - level) * d <= 0

        def hit_tp(level):
            return (fav - level) * d >= 0

        # 1) 寄り付きの窓開け
        if not entry_bar:
            if (o_x - pos.sl) * d <= 0:
                self._close_part(pos, time, o_x, pos.remaining, 'SL_gap')
                return
            if pos.tp1 is not None and not pos.tp1_done and (o_x - pos.tp1) * d >= 0:
                self._take_tp1(pos, time, o_x)
                if pos not in self.open:
                    return
            if pos.tp is not None and (o_x - pos.tp) * d >= 0:
                self._close_part(pos, time, o_x, pos.remaining, 'TP_gap')
                return

        # 2) 損切り優先
        if hit_sl(pos.sl):
            self._close_part(pos, time, pos.sl, pos.remaining, 'SL' if pos.sl == pos.initial_sl else 'TRAIL')
            return
        if entry_bar:
            pos.bars_held += 1
            return

        # 3) 部分利確 → 建値移動（同じ足で建値に戻っていれば約定）
        if pos.tp1 is not None and not pos.tp1_done and hit_tp(pos.tp1):
            self._take_tp1(pos, time, pos.tp1)
            if pos not in self.open:
                return
            if hit_sl(pos.sl):
                self._close_part(pos, time, pos.sl, pos.remaining, 'BE')
                return

        # 4) 最終利確
        if pos.tp is not None and hit_tp(pos.tp):
            self._close_part(pos, time, pos.tp, pos.remaining, 'TP')
            return
        pos.bars_held += 1

    def _take_tp1(self, pos, time, price):
        pos.tp1_done = True
        self._close_part(pos, time, price, pos.tp1_frac, 'TP1')
        if pos in self.open and pos.be_after_tp1:
            be = pos.entry_price + pos.direction * pos.be_offset
            if (be - pos.sl) * pos.direction > 0:
                pos.sl = be


def trade_record(pos, symbol=''):
    """決済済み建玉 → 集計用の辞書"""
    last = pos.exits[-1] if pos.exits else (None, None, 0, '')
    return {
        'symbol': symbol,
        'entry_time': pos.entry_time,
        'exit_time': last[0],
        'direction': pos.direction,
        'entry': pos.entry_price,
        'initial_sl': pos.initial_sl,
        'risk': pos.risk,
        'pnl_r': pos.realized_r,
        'exit_reason': '+'.join(e[3] for e in pos.exits),
        'bars_held': pos.bars_held,
        'mfe_r': pos.mfe_r,
        'mae_r': pos.mae_r,
        **{f'm_{k}': v for k, v in pos.meta.items()},
    }
