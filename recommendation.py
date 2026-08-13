"""买卖价位建议：与桌面 EXE 同一套口径。

- 评级：四策略(三维复合/K线/缠论/波浪)买入信号数 >=2 积极关注 / 1 关注 / 0 观望
- 目标价：顺势类(三维复合/缠论/波浪)看 60 日前高，+2ATR 兜底，目标2 为 +4ATR 延伸；
  K线形态看布林中轨/上轨(+1.5ATR/+2.5ATR)
- 止损：K线形态 2.0×ATR，其余 2.5×ATR（不低于 20 日支撑-ATR，且留至少 3% 空间）
- 贴近前低(现价距支撑 <=0.5×ATR)时：有信号按现价买入，无信号等回踩确认位
"""
from __future__ import annotations

import math

import pandas as pd

from strategies.core_indicators import atr_series, bollinger_series, ema_series, rsi_series

STRATEGY_KEYS = [
    "三维复合(趋势+回归+量价)",
    "K线形态(15种)",
    "缠论(分型笔中枢)",
    "波浪理论(ABC回调)",
]


def _num(value, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(v) else v


def price_levels(df: pd.DataFrame) -> dict:
    close, high, low = df["close"], df["high"], df["low"]
    atr = float(atr_series(high, low, close, 14).iloc[-1])
    bb_mid, bb_upper, bb_lower = bollinger_series(close, 20, 2.0)
    return {
        "close": float(close.iloc[-1]),
        "atr": atr,
        "bb_mid": float(bb_mid.iloc[-1]),
        "bb_upper": float(bb_upper.iloc[-1]),
        "bb_lower": float(bb_lower.iloc[-1]),
        "ma20": float(ema_series(close, 20).iloc[-1]),
        "ma60": float(ema_series(close, 60).iloc[-1]),
        "rsi14": float(rsi_series(close, 14).iloc[-1]),
        "support20": float(low.rolling(20).min().iloc[-1]),
        "resist60": float(high.rolling(60).max().iloc[-1]),
        "last_date": str(df.index[-1].date()),
    }


def targets_for(pl: dict, strategy: str) -> tuple[float, float]:
    close = pl["close"]
    atr = _num(pl.get("atr"), close * 0.03)
    if strategy == "K线形态(15种)":
        bb_mid = _num(pl.get("bb_mid"), close)
        bb_upper = _num(pl.get("bb_upper"), close + 2.0 * atr)
        t1 = max(bb_mid, close + 1.5 * atr)
        t2 = max(bb_upper, close + 2.5 * atr, t1)
    else:
        resist = _num(pl.get("resist60"), 0.0)
        t1 = max(resist, close + 2.0 * atr)
        t2 = max(close + 4.0 * atr, t1)
    return round(t1, 2), round(t2, 2)


def stop_for(pl: dict, strategy: str) -> float:
    close = pl["close"]
    atr = _num(pl.get("atr"), close * 0.03)
    mult = 2.0 if strategy == "K线形态(15种)" else 2.5
    support20 = _num(pl.get("support20"), close * 0.8)
    stop = round(max(close - mult * atr, support20 - atr), 2)
    if stop >= close * 0.97:
        stop = round(close * 0.93, 2)
    return stop


def build_recommendation(pl: dict, n_buy: int, sig_vals: list[int] | None = None) -> dict:
    close, atr = pl["close"], pl["atr"]
    support_ref = max(
        _num(pl.get("support20"), close * 0.95),
        _num(pl.get("bb_lower"), close * 0.95),
    )
    dist_atr = (close - support_ref) / atr if atr > 0 else 99.0
    near_low = dist_atr <= 0.5
    if near_low:
        if n_buy >= 2:
            rating, buy_price = "积极关注", round(close, 2)
        elif n_buy == 1:
            rating, buy_price = "关注", round(close, 2)
        else:
            rating, buy_price = "观望", round(max(support_ref, close * 0.99), 2)
    else:
        if n_buy >= 2:
            rating, buy_price = "积极关注", round(max(support_ref, close * 0.985), 2)
        elif n_buy == 1:
            rating, buy_price = "关注", round(max(support_ref, close * 0.99), 2)
        else:
            rating, buy_price = "观望", round(support_ref, 2)

    cands = {key: targets_for(pl, key) for key in STRATEGY_KEYS}
    if sig_vals:
        active = [key for key, v in zip(STRATEGY_KEYS, sig_vals) if v]
        chosen = min(active or cands, key=lambda k: cands[k][0])
    else:
        chosen = min(cands, key=lambda k: cands[k][0])
    target1, target2 = targets_for(pl, chosen)
    stop = stop_for(pl, chosen)
    return {
        "rating": rating,
        "buy": buy_price,
        "t1": target1,
        "t2": target2,
        "stop": stop,
        "chosen": chosen,
    }
