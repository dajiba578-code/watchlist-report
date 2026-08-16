"""第 5 套信号：TradingAgents signals 引擎（交叉验证）。

来源：trading-agents skill（gaaiyun/TradingAgents-OpenClaw-Skill 的 signals.py），
核心逻辑保持一致：RSI / MACD / MA排列(20/50/200) / 布林带 / OBV / ATR 加权投票，
输出 BUY / SELL / HOLD + 置信度 + 各指标贡献解释。

与 skill 原版的差异：数据由本项目 market_data（东财/腾讯，国内直连免翻墙）提供，
不依赖 yfinance；目标价/止损仍用项目 recommendation 口径。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line})


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return pd.DataFrame({
        "mid": mid,
        "upper": mid + n_std * std,
        "lower": mid - n_std * std,
    })


def moving_averages(close: pd.Series, windows=(20, 50, 200)) -> pd.DataFrame:
    return pd.DataFrame({f"ma{w}": close.rolling(w).mean() for w in windows})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume：资金流方向指标。"""
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


@dataclass
class SignalContribution:
    indicator: str
    value: float
    direction: str  # bullish / bearish / neutral
    weight: float
    rationale: str


def aggregate_signals(df: pd.DataFrame):
    """把多个技术指标的最新一日信号聚合成交易方向 + 置信度。

    返回 (action, confidence, contributions)：
    action: BUY / SELL / HOLD
    confidence: 0~1
    contributions: 每个指标的解释列表
    """
    close = df["close"]
    high = df.get("high", close)
    low = df.get("low", close)
    volume = df.get("volume", pd.Series([np.nan] * len(df)))

    contribs: list[SignalContribution] = []

    rsi_val = rsi(close).iloc[-1]
    if rsi_val < 30:
        contribs.append(SignalContribution("RSI", float(rsi_val), "bullish", 1.0, "RSI<30 超卖，常见反弹信号"))
    elif rsi_val > 70:
        contribs.append(SignalContribution("RSI", float(rsi_val), "bearish", 1.0, "RSI>70 超买，常见回调信号"))
    else:
        contribs.append(SignalContribution("RSI", float(rsi_val), "neutral", 0.3, f"RSI={rsi_val:.1f}，中性区间"))

    m = macd(close).iloc[-1]
    if m["macd"] > m["signal"] and m["hist"] > 0:
        contribs.append(SignalContribution("MACD", float(m["hist"]), "bullish", 1.0, "MACD 上穿信号线且柱状图正，趋势上行"))
    elif m["macd"] < m["signal"] and m["hist"] < 0:
        contribs.append(SignalContribution("MACD", float(m["hist"]), "bearish", 1.0, "MACD 下穿信号线且柱状图负，趋势下行"))
    else:
        contribs.append(SignalContribution("MACD", float(m["hist"]), "neutral", 0.3, "MACD 与信号线交汇中，方向不明"))

    mas = moving_averages(close, windows=(20, 50, 200)).iloc[-1]
    price = close.iloc[-1]
    if not mas.isna().any():
        if price > mas["ma20"] > mas["ma50"] > mas["ma200"]:
            contribs.append(SignalContribution("MA-stack", float(price), "bullish", 1.2, "价格在 MA20>MA50>MA200 上方，多头排列"))
        elif price < mas["ma20"] < mas["ma50"] < mas["ma200"]:
            contribs.append(SignalContribution("MA-stack", float(price), "bearish", 1.2, "价格在 MA20<MA50<MA200 下方，空头排列"))
        else:
            contribs.append(SignalContribution("MA-stack", float(price), "neutral", 0.3, "MA 排列纠缠，趋势不明"))

    bb = bollinger(close).iloc[-1]
    if not pd.isna(bb["upper"]):
        if price >= bb["upper"]:
            contribs.append(SignalContribution("Bollinger", float(price), "bearish", 0.8, "价格触及/突破上轨，短期超买"))
        elif price <= bb["lower"]:
            contribs.append(SignalContribution("Bollinger", float(price), "bullish", 0.8, "价格触及/跌破下轨，短期超卖"))
        else:
            contribs.append(SignalContribution("Bollinger", float(price), "neutral", 0.2, "价格位于布林带中部"))

    if volume.notna().any():
        o = obv(close, volume.fillna(0))
        if len(o) >= 6:
            slope = o.iloc[-1] - o.iloc[-6]
            if slope > 0:
                contribs.append(SignalContribution("OBV", float(slope), "bullish", 0.6, "近 5 日 OBV 上升，资金净流入"))
            elif slope < 0:
                contribs.append(SignalContribution("OBV", float(slope), "bearish", 0.6, "近 5 日 OBV 下降，资金净流出"))
            else:
                contribs.append(SignalContribution("OBV", 0.0, "neutral", 0.2, "OBV 横盘"))

    score = 0.0
    total_weight = 0.0
    for c in contribs:
        s = {"bullish": 1, "bearish": -1, "neutral": 0}[c.direction]
        score += s * c.weight
        total_weight += c.weight

    normalized = score / total_weight if total_weight > 0 else 0.0
    if normalized >= 0.35:
        action = "BUY"
    elif normalized <= -0.35:
        action = "SELL"
    else:
        action = "HOLD"
    confidence = min(abs(normalized), 1.0)
    return action, float(confidence), contribs
