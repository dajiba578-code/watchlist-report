"""策略：K 线形态（candlestick）。

依据 vibe-trading skill 的 candlestick 技能实现 15 种经典形态：
- 单根 5 种：锤子线、倒锤子、射击之星、十字星、纺锤线
- 双根 5 种：看涨/看跌吞没、看涨/看跌孕育、刺透线、乌云盖顶
- 三根 4 种：晨星、暮星、三白兵、三黑鸦
看涨 +1、看跌 -1 汇总打分；总分 >0 做多，否则空仓（A 股多头）。
附加风控过滤：
- 趋势过滤：仅当收盘价站上 MA20 时允许做多（过滤下跌趋势中的假形态）
- 量能确认：仅当当日成交量 > 20 日均量 × vol_ratio 时允许做多
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def compute_signals(
    df: pd.DataFrame,
    body_pct: float = 0.1,
    shadow_ratio: float = 2.0,
    trend_ma: int = 20,
    vol_ratio: float = 1.2,
) -> pd.Series:
    """返回 0/1 信号序列：1=看涨形态占优，0=空仓。"""
    o = df["open"]
    h = df["high"]
    l = df["low"]
    c = df["close"]

    body = (c - o).abs()
    rng = (h - l).replace(0.0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    body_r = body / rng

    score = pd.Series(0.0, index=df.index)

    # --- 单根 ---
    hammer = (lower >= shadow_ratio * body) & (upper <= body * 0.5) & (body > 0)
    inverted_hammer = (upper >= shadow_ratio * body) & (lower <= body * 0.5) & (body > 0)
    shooting_star = inverted_hammer & (c.shift(1) < c)  # 需出现在上涨之后
    doji = body_r <= body_pct
    spinning = (body_r <= 0.3) & ~doji & (upper > body * 0.5) & (lower > body * 0.5) & (body > 0)
    score += hammer.astype(float) + inverted_hammer.astype(float) - shooting_star.astype(float)

    # --- 双根 ---
    prev_bear = c.shift(1) < o.shift(1)
    prev_bull = c.shift(1) > o.shift(1)
    engulf_bull = prev_bear & (c >= o.shift(1)) & (o <= c.shift(1)) & (c > o)
    engulf_bear = prev_bull & (c <= o.shift(1)) & (o >= c.shift(1)) & (c < o)
    harami_bull = prev_bull & (c <= o.shift(1)) & (o >= c.shift(1)) & (c > o) & (body < body.shift(1) * 0.7)
    harami_bear = prev_bear & (c >= o.shift(1)) & (o <= c.shift(1)) & (c < o) & (body < body.shift(1) * 0.7)
    mid_prev = (o.shift(1) + c.shift(1)) / 2
    piercing = prev_bear & (c > mid_prev) & (c < o.shift(1)) & (c > o)
    dark_cloud = prev_bull & (c < mid_prev) & (c > o.shift(1)) & (c < o)
    score += (
        engulf_bull.astype(float) - engulf_bear.astype(float)
        + harami_bull.astype(float) - harami_bear.astype(float)
        + piercing.astype(float) - dark_cloud.astype(float)
    )

    # --- 三根 ---
    small_body1 = body.shift(1) <= body_pct * rng.shift(1)
    morning = (c.shift(2) < o.shift(2)) & small_body1 & (c > mid_prev.shift(1)) & (c > o)
    evening = (c.shift(2) > o.shift(2)) & small_body1 & (c < mid_prev.shift(1)) & (c < o)
    white_soldiers = (c > c.shift(1)) & (c.shift(1) > c.shift(2)) & (o > o.shift(1)) & (o.shift(1) > o.shift(2)) & (c > o)
    black_crows = (c < c.shift(1)) & (c.shift(1) < c.shift(2)) & (o < o.shift(1)) & (o.shift(1) < o.shift(2)) & (c < o)
    score += (
        morning.astype(float) - evening.astype(float)
        + white_soldiers.astype(float) - black_crows.astype(float)
    )

    # 风控过滤：趋势向上 + 量能放大
    trend_ok = c > c.rolling(trend_ma).mean()
    vol_ma = df["volume"].rolling(trend_ma).mean()
    vol_ok = df["volume"] > vol_ma * vol_ratio
    signal = ((score > 0) & trend_ok & vol_ok).astype(int)
    return signal.fillna(0)


class SignalEngine:
    """K 线形态信号引擎（供回测 runner 加载）。"""

    def __init__(
        self,
        body_pct: float = 0.1,
        shadow_ratio: float = 2.0,
        trend_ma: int = 20,
        vol_ratio: float = 1.2,
    ):
        self.body_pct = body_pct
        self.shadow_ratio = shadow_ratio
        self.trend_ma = trend_ma
        self.vol_ratio = vol_ratio

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                body_pct=self.body_pct,
                shadow_ratio=self.shadow_ratio,
                trend_ma=self.trend_ma,
                vol_ratio=self.vol_ratio,
            )
            for code, df in data_map.items()
        }
