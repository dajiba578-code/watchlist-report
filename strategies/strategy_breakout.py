"""策略三：通道突破（唐奇安通道 + ADX 趋势过滤 + 量能确认 + ATR 移动止损）。

依据 vibe-trading skill 的趋势/突破框架：
- 收盘突破 20 日最高价、ADX(14)>25 且放量（量>1.2 倍 20 日均量）时入场；
- 收盘跌破 10 日最低价，或跌破近 10 日最高收盘 - 2.5*ATR 的移动止损时离场。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from strategies.core_indicators import adx_series, atr_series, donchian_series, sticky_state


class SignalEngine:
    """通道突破信号引擎（供回测 runner 加载）。"""

    def __init__(
        self,
        dc_entry: int = 20,
        dc_exit: int = 10,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        vol_period: int = 20,
        vol_mult: float = 1.2,
        atr_period: int = 14,
        stop_atr: float = 2.5,
    ):
        self.dc_entry = dc_entry
        self.dc_exit = dc_exit
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.vol_period = vol_period
        self.vol_mult = vol_mult
        self.atr_period = atr_period
        self.stop_atr = stop_atr

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                dc_entry=self.dc_entry,
                dc_exit=self.dc_exit,
                adx_period=self.adx_period,
                adx_threshold=self.adx_threshold,
                vol_period=self.vol_period,
                vol_mult=self.vol_mult,
                atr_period=self.atr_period,
                stop_atr=self.stop_atr,
            )
            for code, df in data_map.items()
        }


def compute_signals(
    df: pd.DataFrame,
    dc_entry: int = 20,
    dc_exit: int = 10,
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    vol_period: int = 20,
    vol_mult: float = 1.2,
    atr_period: int = 14,
    stop_atr: float = 2.5,
) -> pd.Series:
    """返回 0/1 信号序列：1=持有，0=空仓。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    dc_high, dc_low = donchian_series(high, low, max(dc_entry, dc_exit))
    entry_high = dc_high.shift(1)
    exit_low = dc_low.shift(1)
    adxv = adx_series(high, low, close, adx_period)
    atrv = atr_series(high, low, close, atr_period)
    vol_ma = volume.rolling(vol_period).mean()

    enter = (close > entry_high) & (adxv > adx_threshold) & (volume >= vol_ma * vol_mult)
    trailing = close.rolling(dc_exit).max() - stop_atr * atrv
    exit_cond = (close < exit_low) | (close < trailing)
    return sticky_state(enter, exit_cond)
