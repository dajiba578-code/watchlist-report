"""策略：波浪理论（elliott-wave，简化自实现）。

依据 vibe-trading skill 的 elliott-wave 技能框架：
- Zigzag 摆动点识别（5% 反转阈值）
- 回调 ABC 完成（回撤 38.2%~78.6%）→ 买点
- 5 浪推动完成 / 反弹无力 → 卖点
采用“宁可错过、不可错判”的保守识别策略（与技能口径一致）。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def _zigzag(close: np.ndarray, pct: float = 0.05) -> list[tuple[int, float, str]]:
    """基于收盘价的百分比 Zigzag：返回 [(索引, 价格, 'up'/'down')]，up=摆动高点, down=摆动低点。"""
    n = len(close)
    if n < 10:
        return []
    swings: list[tuple[int, float, str]] = []
    last_extreme = (0, float(close[0]))
    direction = 0
    for i in range(1, n):
        price = float(close[i])
        if direction >= 0:
            if price >= last_extreme[1]:
                last_extreme = (i, price)
            elif last_extreme[1] - price >= pct * last_extreme[1]:
                swings.append((last_extreme[0], last_extreme[1], "up"))
                last_extreme = (i, price)
                direction = -1
        else:
            if price <= last_extreme[1]:
                last_extreme = (i, price)
            elif price - last_extreme[1] >= pct * last_extreme[1]:
                swings.append((last_extreme[0], last_extreme[1], "down"))
                last_extreme = (i, price)
                direction = 1
    if direction >= 0 and last_extreme[1] > float(close[0]):
        swings.append((last_extreme[0], last_extreme[1], "up"))
    elif direction < 0 and last_extreme[1] < float(close[0]):
        swings.append((last_extreme[0], last_extreme[1], "down"))
    return swings


def compute_signals(
    df: pd.DataFrame,
    zigzag_pct: float = 0.05,
    fib_retrace_min: float = 0.382,
    fib_retrace_max: float = 0.786,
) -> pd.Series:
    """返回 0/1 信号：1=回调到位/持有，0=空仓。"""
    n = len(df)
    sig = np.zeros(n, dtype=np.int64)
    close = df["close"].to_numpy(dtype=float)
    swings = _zigzag(close, zigzag_pct)
    if len(swings) < 4:
        return pd.Series(sig, index=df.index)

    buy_days: list[int] = []
    sell_days: list[int] = []
    last_buy_idx = -1

    for i in range(2, len(swings)):
        typ = swings[i][2]
        idx = swings[i][0]
        price = swings[i][1]
        prev = swings[i - 1]
        prev2 = swings[i - 2]
        if typ == "down" and prev[2] == "up" and prev2[2] == "down":
            # ABC 回调：C 低点回撤 A-B 涨幅的 38.2%~78.6% 视为回调完成
            swing_up = prev[1] - prev2[1]
            if swing_up > 0:
                retrace = (prev[1] - price) / swing_up
                if fib_retrace_min <= retrace <= fib_retrace_max:
                    buy_days.append(idx)
        elif typ == "up" and prev[2] == "down" and prev2[2] == "up":
            # 卖点：反弹创新高但涨幅小于上一段跌幅的一半（反弹无力）
            weak_bounce = (price - prev[1]) < 0.5 * (prev2[1] - prev[1])
            if weak_bounce:
                sell_days.append(idx)

    buy_set = set(buy_days)
    sell_set = set(sell_days)
    state = 0
    last_entry = -1
    for i in range(n):
        if i in buy_set:
            state = 1
            last_entry = i
        if i in sell_set and i - last_entry >= 3:
            state = 0
        sig[i] = state
    return pd.Series(sig, index=df.index)


class SignalEngine:
    """波浪理论信号引擎（供回测 runner 加载）。"""

    def __init__(self, zigzag_pct: float = 0.05, fib_retrace_min: float = 0.382, fib_retrace_max: float = 0.786):
        self.zigzag_pct = zigzag_pct
        self.fib_retrace_min = fib_retrace_min
        self.fib_retrace_max = fib_retrace_max

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        return {
            code: compute_signals(
                df,
                zigzag_pct=self.zigzag_pct,
                fib_retrace_min=self.fib_retrace_min,
                fib_retrace_max=self.fib_retrace_max,
            )
            for code, df in data_map.items()
        }
