"""策略一：趋势跟踪（EMA 金叉/死叉 + ADX 趋势强度 + ATR 破位止损）。

依据 vibe-trading skill 的 technical-basic 趋势维度：
- EMA20 上穿 EMA60 且 ADX(14)>20 视为上升趋势，做多；
- 死叉、或收盘跌破 EMA60 - 2.5*ATR 视为趋势破坏，平仓。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from strategies.core_indicators import adx_series, atr_series, ema_series


class SignalEngine:
    """趋势跟踪信号引擎（供回测 runner 加载）。"""

    def __init__(
        self,
        ema_fast: int = 20,
        ema_slow: int = 60,
        adx_period: int = 14,
        adx_threshold: float = 20.0,
        atr_period: int = 14,
        stop_atr: float = 2.5,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.atr_period = atr_period
        self.stop_atr = stop_atr

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                adx_period=self.adx_period,
                adx_threshold=self.adx_threshold,
                atr_period=self.atr_period,
                stop_atr=self.stop_atr,
            )
            for code, df in data_map.items()
        }


def compute_signals(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_slow: int = 60,
    adx_period: int = 14,
    adx_threshold: float = 20.0,
    atr_period: int = 14,
    stop_atr: float = 2.5,
) -> pd.Series:
    """返回 0/1 信号序列：1=持有/做多，0=空仓。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]

    fast = ema_series(close, ema_fast)
    slow = ema_series(close, ema_slow)
    adxv = adx_series(high, low, close, adx_period)
    atrv = atr_series(high, low, close, atr_period)

    hold = (fast > slow) & (adxv > adx_threshold) & (close >= slow - stop_atr * atrv)
    return hold.astype(int).fillna(0)
