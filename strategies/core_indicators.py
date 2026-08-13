"""共用技术指标库（纯 pandas / numpy 实现，无外部信号库依赖）。

指标口径与 vibe-trading skill 的 technical-basic 一致：
- RSI / ADX 使用 Wilder EWM（alpha=1/period）
- ATR 使用 Wilder EWM 平滑
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema_series(close: pd.Series, span: int) -> pd.Series:
    """指数移动平均。"""
    return close.ewm(span=span, adjust=False).mean()


def rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI（Wilder EWM），范围 0-100。"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    out = out.where(avg_loss != 0.0, 100.0)
    return out.fillna(50.0)


def adx_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX 全链路：+DM/-DM -> TR -> Wilder 平滑 -> +DI/-DI -> DX -> ADX。"""
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

    alpha = 1.0 / period
    smoothed_tr = tr.ewm(alpha=alpha, min_periods=period).mean()
    smoothed_pdm = plus_dm.ewm(alpha=alpha, min_periods=period).mean()
    smoothed_mdm = minus_dm.ewm(alpha=alpha, min_periods=period).mean()

    plus_di = 100.0 * smoothed_pdm / smoothed_tr.replace(0.0, np.nan)
    minus_di = 100.0 * smoothed_mdm / smoothed_tr.replace(0.0, np.nan)
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0.0, np.nan)
    adx = dx.ewm(alpha=alpha, min_periods=period).mean()
    return adx.fillna(0.0)


def bollinger_series(close: pd.Series, window: int = 20, num_std: float = 2.0):
    """布林带：返回 (中轨, 上轨, 下轨)。"""
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return mid, mid + num_std * std, mid - num_std * std


def atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR（Wilder EWM）。"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period).mean()


def donchian_series(high: pd.Series, low: pd.Series, window: int):
    """唐奇安通道：返回 (window 期最高, window 期最低)。"""
    return high.rolling(window).max(), low.rolling(window).min()


def sticky_state(enter: pd.Series, exit_cond: pd.Series) -> pd.Series:
    """向量化持仓状态机：入场后保持 1，直到出场条件成立变为 0。

    逐根 bar 顺序扫描，语义与真实持仓一致：出场优先于入场。
    """
    e = enter.fillna(False).to_numpy(dtype=bool)
    x = exit_cond.fillna(False).to_numpy(dtype=bool)
    out = np.zeros(len(e), dtype=np.int64)
    pos = 0
    for i in range(len(e)):
        if x[i] and pos:
            pos = 0
        elif e[i] and not pos:
            pos = 1
        out[i] = pos
    return pd.Series(out, index=enter.index)
