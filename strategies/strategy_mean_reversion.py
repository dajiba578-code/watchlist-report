"""策略二：均值回归（布林带下轨 + RSI 超卖 + 量能确认）。

依据 vibe-trading skill 的 technical-basic 均值回归维度：
- 收盘跌破布林下轨(20,2)、RSI(14)<32 且放量（量>20日均量）时入场；
- 收盘回到中轨上方、RSI>60、或继续跌破下轨 2.5*ATR 时止损离场。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from strategies.core_indicators import atr_series, bollinger_series, rsi_series, sticky_state


class SignalEngine:
    """均值回归信号引擎（供回测 runner 加载）。"""

    def __init__(
        self,
        bb_window: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 32.0,
        rsi_exit: float = 60.0,
        vol_period: int = 20,
        vol_mult: float = 1.0,
        atr_period: int = 14,
        stop_atr: float = 2.5,
    ):
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.vol_period = vol_period
        self.vol_mult = vol_mult
        self.atr_period = atr_period
        self.stop_atr = stop_atr

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                bb_window=self.bb_window,
                bb_std=self.bb_std,
                rsi_period=self.rsi_period,
                rsi_oversold=self.rsi_oversold,
                rsi_exit=self.rsi_exit,
                vol_period=self.vol_period,
                vol_mult=self.vol_mult,
                atr_period=self.atr_period,
                stop_atr=self.stop_atr,
            )
            for code, df in data_map.items()
        }


def compute_signals(
    df: pd.DataFrame,
    bb_window: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_oversold: float = 32.0,
    rsi_exit: float = 60.0,
    vol_period: int = 20,
    vol_mult: float = 1.0,
    atr_period: int = 14,
    stop_atr: float = 2.5,
) -> pd.Series:
    """返回 0/1 信号序列：1=持有，0=空仓。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    mid, _upper, lower = bollinger_series(close, bb_window, bb_std)
    rsi_v = rsi_series(close, rsi_period)
    atrv = atr_series(high, low, close, atr_period)
    vol_ma = volume.rolling(vol_period).mean()

    enter = (close < lower) & (rsi_v < rsi_oversold) & (volume >= vol_ma * vol_mult)
    exit_cond = (close > mid) | (rsi_v > rsi_exit) | (close < lower - stop_atr * atrv)
    return sticky_state(enter, exit_cond)
