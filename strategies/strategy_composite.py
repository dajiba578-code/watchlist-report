"""策略：三维复合（technical-basic 完整版：趋势 + 均值回归 + 量价投票）。

依据 vibe-trading skill 的 technical-basic 技能：
- 趋势维度：EMA(12/26) 金叉/死叉 + ADX(14) 趋势强度
- 均值回归维度：布林带(20,2) + RSI(14) 超买超卖
- 量价维度：OBV 与 OBV 均线 + 量比确认
- 投票逻辑：趋势看多或超卖，且量价看多、未超买 → 做多（A 股多头）
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    alpha = 1 / period
    smoothed_tr = tr.ewm(alpha=alpha, min_periods=period).mean()
    smoothed_pdm = plus_dm.ewm(alpha=alpha, min_periods=period).mean()
    smoothed_mdm = minus_dm.ewm(alpha=alpha, min_periods=period).mean()
    plus_di = 100 * smoothed_pdm / smoothed_tr
    minus_di = 100 * smoothed_mdm / smoothed_tr
    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=alpha, min_periods=period).mean()
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx})


def compute_bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + num_std * std, "bb_lower": mid - num_std * std})


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    sign = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (volume * sign).cumsum()


def compute_signals(
    df: pd.DataFrame,
    ema_fast: int = 12,
    ema_slow: int = 26,
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    bb_window: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    vol_ma_period: int = 20,
    obv_ma_period: int = 20,
) -> pd.Series:
    """返回 0/1 信号：三维投票看多=1，否则空仓。"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    ema_f = close.ewm(span=ema_fast, adjust=False).mean()
    ema_s = close.ewm(span=ema_slow, adjust=False).mean()
    adx = compute_adx(high, low, close, adx_period)["adx"]
    trend_bull = (ema_f > ema_s) & (adx > adx_threshold)

    bb = compute_bollinger(close, bb_window, bb_std)
    rsi = compute_rsi(close, rsi_period)
    mr_oversold = (close < bb["bb_lower"]) & (rsi < rsi_oversold)
    mr_overbought = (close > bb["bb_upper"]) & (rsi > rsi_overbought)

    obv = compute_obv(close, volume)
    obv_ma = obv.rolling(obv_ma_period).mean()
    vol_bull = obv > obv_ma

    buy = (trend_bull | mr_oversold) & vol_bull & ~mr_overbought
    return buy.astype(int).fillna(0)


class SignalEngine:
    """三维复合信号引擎（供回测 runner 加载）。"""

    def __init__(
        self,
        ema_fast: int = 12,
        ema_slow: int = 26,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        bb_window: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        vol_ma_period: int = 20,
        obv_ma_period: int = 20,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.bb_window = bb_window
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.vol_ma_period = vol_ma_period
        self.obv_ma_period = obv_ma_period

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                ema_fast=self.ema_fast,
                ema_slow=self.ema_slow,
                adx_period=self.adx_period,
                adx_threshold=self.adx_threshold,
                bb_window=self.bb_window,
                bb_std=self.bb_std,
                rsi_period=self.rsi_period,
                rsi_oversold=self.rsi_oversold,
                rsi_overbought=self.rsi_overbought,
                vol_ma_period=self.vol_ma_period,
                obv_ma_period=self.obv_ma_period,
            )
            for code, df in data_map.items()
        }
