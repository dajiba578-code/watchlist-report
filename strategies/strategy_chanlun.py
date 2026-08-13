"""策略四：缠论（分型→笔→中枢→买卖点）。

依据 vibe-trading skill 的 chanlun 框架自实现（纯 pandas/numpy，不依赖 czsc/TA-Lib）：
- K 线包含处理（含合并）
- 顶/底分型识别
- 笔：顶底分型交替、间隔 >=1 根合并 K、顶必须高于相邻底
- 中枢：连续 3 笔的重叠区间（zs_low < zs_high 才有效）
- 买点：一买（新低+下跌背驰）、二买（回调不破前低）、三买（回踩不进入中枢）
- 卖点：顶背驰 或 跌破最近底分型低点（破位止损）
信号约定：1=持有/做多，0=空仓（A 股多头，不卖空）。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _merge_k(high: np.ndarray, low: np.ndarray):
    """K 线包含处理（含合并）。返回 (合并高点, 合并低点, 各合并K对应原始索引)。"""
    mh: list[float] = []
    ml: list[float] = []
    midx: list[int] = []
    direction = 0  # 1=向上, -1=向下（决定包含方向）
    for i in range(len(high)):
        if not mh:
            mh.append(float(high[i]))
            ml.append(float(low[i]))
            midx.append(i)
            continue
        contained = (high[i] >= mh[-1] and low[i] <= ml[-1]) or (high[i] <= mh[-1] and low[i] >= ml[-1])
        if contained:
            if direction >= 0:
                mh[-1] = max(mh[-1], float(high[i]))
                ml[-1] = max(ml[-1], float(low[i]))
            else:
                mh[-1] = min(mh[-1], float(high[i]))
                ml[-1] = min(ml[-1], float(low[i]))
        else:
            direction = 1 if high[i] > mh[-1] else -1
            mh.append(float(high[i]))
            ml.append(float(low[i]))
            midx.append(i)
    return np.asarray(mh), np.asarray(ml), np.asarray(midx)


def _build_bis(mh: np.ndarray, ml: np.ndarray, midx: np.ndarray, min_gap: int = 2) -> list[list]:
    """分型识别并构建笔序列。每笔: [合并索引, 类型('top'/'bot'), 价格, 原始索引]"""
    pts: list[tuple[int, str, float]] = []
    for j in range(1, len(mh) - 1):
        if mh[j] > mh[j - 1] and mh[j] > mh[j + 1]:
            pts.append((j, "top", float(mh[j])))
        if ml[j] < ml[j - 1] and ml[j] < ml[j + 1]:
            pts.append((j, "bot", float(ml[j])))

    bis: list[list] = []
    for j, typ, p in sorted(pts, key=lambda x: x[0]):
        if not bis:
            bis.append([j, typ, p, int(midx[j])])
            continue
        lj, ltyp, lp, _lidx = bis[-1]
        if typ == ltyp:
            if (typ == "top" and p >= lp) or (typ == "bot" and p <= lp):
                bis[-1] = [j, typ, p, int(midx[j])]
            continue
        if j - lj < min_gap:
            continue  # 顶底分型之间至少隔 min_gap 根合并 K
        if (typ == "top" and p > lp) or (typ == "bot" and p < lp):
            bis.append([j, typ, p, int(midx[j])])
    return bis


def _last_zs(bis: list[list], n: int = 3):
    """最近连续 n 笔的重叠中枢，返回 (zs_low, zs_high, 起始笔序号) 或 None。"""
    if len(bis) < n:
        return None
    for start in range(len(bis) - n, -1, -1):
        seg = bis[start : start + n]
        ranges = []
        prev_p = None
        for _j, _typ, p, _idx in seg:
            if prev_p is not None:
                ranges.append((min(prev_p, p), max(prev_p, p)))
            prev_p = p
        if not ranges:
            continue
        zs_low = max(r[0] for r in ranges)
        zs_high = min(r[1] for r in ranges)
        if zs_low < zs_high:
            return zs_low, zs_high, start
    return None


def compute_signals(
    df: pd.DataFrame,
    min_gap: int = 2,
    zs_bis: int = 3,
    use_second_buy: bool = False,
    min_hold: int = 5,
) -> pd.Series:
    """返回 0/1 信号序列：1=持有/做多，0=空仓。"""
    n = len(df)
    sig = np.zeros(n, dtype=np.int64)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    mh, ml, midx = _merge_k(high, low)
    bis = _build_bis(mh, ml, midx, min_gap)
    if len(bis) < 3:
        return pd.Series(sig, index=df.index)

    buy_days: list[int] = []
    sell_days: list[int] = []
    prev_bot_price: float | None = None  # 上一个底分型低点（一买参考）
    prev_drop: float | None = None  # 上一段下跌笔的跌幅

    for i in range(1, len(bis)):
        typ = bis[i][1]
        price = bis[i][2]
        day = int(bis[i][3])
        prev_typ = bis[i - 1][1]
        prev_price = bis[i - 1][2]

        if typ == "bot":
            drop = prev_price - price if prev_price > price else 0.0
            zs = _last_zs(bis[: i + 1], zs_bis)
            buy_reason = None
            if zs is not None and price > zs[1]:
                buy_reason = "三买"  # 回踩不进入中枢
            elif prev_bot_price is not None:
                if price < prev_bot_price and prev_drop is not None and drop < prev_drop:
                    buy_reason = "一买"  # 新低 + 下跌背驰
                elif use_second_buy and price > prev_bot_price:
                    buy_reason = "二买"  # 回调不破前低
            if buy_reason is not None:
                buy_days.append(day)
            prev_bot_price = price
            prev_drop = drop

        elif typ == "top":
            gain = price - prev_price if price > prev_price else 0.0
            zs = _last_zs(bis[: i + 1], zs_bis)
            sell = False
            # 顶背驰：本段上涨幅度小于上一段上涨幅度
            if i >= 3 and bis[i - 3][1] == "bot":
                prev_gain = bis[i - 2][2] - bis[i - 3][2]
                if prev_gain > 0 and gain < prev_gain:
                    sell = True
            if zs is not None and price < zs[1]:
                sell = True  # 跌破中枢上沿
            if sell:
                sell_days.append(day)

    # 前向持仓状态：买点日起为 1，卖点日起为 0
    buy_set = set(buy_days)
    sell_set = set(sell_days)
    state = 0
    last_entry = -1
    for i in range(n):
        if i in buy_set:
            state = 1
            last_entry = i
        if i in sell_set and (i - last_entry >= min_hold or last_entry < 0):
            state = 0
        sig[i] = state
    return pd.Series(sig, index=df.index)


class SignalEngine:
    """缠论信号引擎（供回测 runner 加载）。"""

    def __init__(self, min_gap: int = 2, zs_bis: int = 3, use_second_buy: bool = False, min_hold: int = 5):
        self.min_gap = min_gap
        self.zs_bis = zs_bis
        self.use_second_buy = use_second_buy
        self.min_hold = min_hold

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                min_gap=self.min_gap,
                zs_bis=self.zs_bis,
                use_second_buy=self.use_second_buy,
                min_hold=self.min_hold,
            )
            for code, df in data_map.items()
        }
