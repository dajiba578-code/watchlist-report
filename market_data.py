"""免费行情抓取：东方财富(主) + 腾讯/新浪(备)，A股/美股国内直连，无需翻墙。

日线：东方财富前复权(主) -> 腾讯A股/新浪美股(备用)
实时：腾讯批量行情（含涨跌幅/PE/总市值）
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
US_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get"
QUOTE_URL = "https://qt.gtimg.cn/q="
SINA_A_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData"
SINA_US_KLINE_URL = (
    "https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20x=/US_MinKService.getDailyK"
)
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

MACRO_SYMBOLS = [
    ("上证指数", "sh000001"),
    ("深证成指", "sz399001"),
    ("创业板指", "sz399006"),
    ("道琼斯", "usDJI"),
    ("纳斯达克", "usIXIC"),
    ("标普500", "usINX"),
    ("VIX", "usVIX"),
]


def _get(url: str, timeout: int = 20, encoding: str = "gbk") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(encoding, errors="replace")


def tencent_symbol(code: str) -> str:
    c = code.upper()
    if c.endswith(".US"):
        return "us" + c.removesuffix(".US")
    digits, _, suffix = c.partition(".")
    if suffix in {"SH", "SZ"}:
        return suffix.lower() + digits
    return ""


def is_us(code: str) -> bool:
    return code.upper().endswith(".US")


def ny_now() -> datetime:
    """美东当前时间（按美国夏令时规则手动换算，无第三方依赖）。"""
    now_utc = datetime.utcnow()
    year = now_utc.year

    def second_sunday(month: int) -> datetime:
        d = datetime(year, month, 1)
        offset = (6 - d.weekday()) % 7
        return d + timedelta(days=offset + 7)

    def first_sunday(month: int) -> datetime:
        d = datetime(year, month, 1)
        offset = (6 - d.weekday()) % 7
        return d + timedelta(days=offset)

    dst_start = second_sunday(3)
    dst_end = first_sunday(11)
    offset_h = 4 if dst_start <= now_utc < dst_end else 5
    return now_utc - timedelta(hours=offset_h)


def eastmoney_secid(code: str) -> str:
    """东财 secid：A股 1.600519 / 0.300750，美股 105.AAPL。"""
    c = code.upper()
    if c.endswith(".US"):
        return "105." + c.removesuffix(".US")
    digits, _, suffix = c.partition(".")
    return ("1." if suffix == "SH" else "0.") + digits


def _fetch_eastmoney(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    secid = eastmoney_secid(code)
    beg = start_date.replace("-", "")
    end = end_date.replace("-", "")
    url = (
        f"{EM_KLINE_URL}?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg={beg}&end={end}"
    )
    raw = _get(url, encoding="utf-8")
    data = json.loads(raw)
    kl = (data.get("data") or {}).get("klines") or []
    if not kl:
        raise ValueError(f"东财 {code} 无数据")
    rows = []
    for line in kl:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    return pd.DataFrame(rows)


def _parse_tencent_bars(data: dict, tcode: str) -> list:
    node = data.get("data", {}).get(tcode, {})
    for key in ("qfqday", "day", "qfqweek", "week"):
        if key in node:
            return node[key]
    return []


def _fetch_tencent(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    tcode = tencent_symbol(code)
    if not tcode:
        raise ValueError(f"不支持的代码: {code}")
    url = f"{US_KLINE_URL if is_us(code) else KLINE_URL}?param={tcode},day,{start_date},{end_date},640,qfq"
    raw = _get(url, encoding="utf-8")
    data = json.loads(raw)
    bars = _parse_tencent_bars(data, tcode)
    if not bars:
        raise ValueError(f"腾讯 {code} 无数据")
    rows = []
    for b in bars:
        try:
            rows.append(
                {
                    "date": b[0],
                    "open": float(b[1]),
                    "close": float(b[2]),
                    "high": float(b[3]),
                    "low": float(b[4]),
                    "volume": float(b[5]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"腾讯 {code} 解析为空")
    return df


def _fetch_sina_a(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    sym = tencent_symbol(code)
    if not sym:
        raise ValueError(f"不支持的代码: {code}")
    url = f"{SINA_A_KLINE_URL}?symbol={sym}&scale=240&ma=no&datalen=1023"
    raw = _get(url, encoding="utf-8")
    start_i = raw.find("[")
    end_i = raw.rfind("]")
    if start_i < 0 or end_i <= start_i:
        raise ValueError(f"sina {code} 格式异常")
    bars = json.loads(raw[start_i : end_i + 1])
    rows = []
    for b in bars:
        try:
            rows.append(
                {
                    "date": b["day"],
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b["volume"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    return df


def _fetch_sina_us(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    ticker = code.upper().removesuffix(".US").replace(".", "-")
    url = f"{SINA_US_KLINE_URL}?symbol={ticker}&___qn=3"
    raw = _get(url, encoding="utf-8")
    start_i = raw.find("[")
    end_i = raw.rfind("]")
    if start_i < 0 or end_i <= start_i:
        raise ValueError(f"sina {code} 格式异常")
    bars = json.loads(raw[start_i : end_i + 1])
    rows = []
    for b in bars:
        try:
            rows.append(
                {
                    "date": b["d"],
                    "open": float(b["o"]),
                    "high": float(b["h"]),
                    "low": float(b["l"]),
                    "close": float(b["c"]),
                    "volume": float(b["v"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    return df


def _to_std(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "close"]).drop_duplicates(subset="date").set_index("date").sort_index()
    df = df.loc[start_date:end_date]
    return df[["open", "high", "low", "close", "volume"]]


def fetch_daily(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """日线抓取：东财(主) -> 腾讯A/新浪美股(备)，返回标准 OHLCV DataFrame（index=date）。"""
    errors: list[str] = []
    fns = (
        [_fetch_eastmoney, _fetch_sina_us]
        if is_us(code)
        else [_fetch_eastmoney, _fetch_tencent, _fetch_sina_a]
    )
    for fn in fns:
        try:
            df = _to_std(fn(code, start_date, end_date), start_date, end_date)
            if df is not None and len(df) >= 30:
                return df
            errors.append(f"{fn.__name__} 数据过少")
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
    raise RuntimeError(f"{code} 行情获取失败: " + " | ".join(errors))


def _parse_quote_field(parts: list, idx: int, default: float | None = None) -> float | None:
    try:
        if idx < len(parts) and parts[idx] not in ("", "-"):
            return float(parts[idx])
    except (TypeError, ValueError):
        pass
    return default


def fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量实时行情（腾讯），返回 {code: {price, pct, prev_close, high, low, pe, mcap, name}}。"""
    out: dict[str, dict] = {}
    if not codes:
        return out
    symbols = ",".join(tencent_symbol(c) for c in codes)
    try:
        raw = _get(QUOTE_URL + symbols)
        for line in raw.strip().split(";"):
            line = line.strip()
            if "=" not in line or not line.startswith("v_"):
                continue
            payload = line.split("=", 1)[1].strip().strip('"')
            parts = payload.split("~")
            if len(parts) < 10:
                continue
            sym = line.split("=", 1)[0].removeprefix("v_")
            code = next((c for c in codes if tencent_symbol(c) == sym), None)
            if not code:
                continue
            out[code] = {
                "name": parts[1],
                "price": _parse_quote_field(parts, 3),
                "prev_close": _parse_quote_field(parts, 4),
                "open": _parse_quote_field(parts, 5),
                "pct": _parse_quote_field(parts, 32),
                "high": _parse_quote_field(parts, 33),
                "low": _parse_quote_field(parts, 34),
                "pe": _parse_quote_field(parts, 39),
                "mcap": _parse_quote_field(parts, 45),
            }
    except Exception:
        pass
    return out


def fetch_macro() -> list[dict]:
    """主要指数实时行情。"""
    items: list[dict] = []
    symbols = ",".join(s for _, s in MACRO_SYMBOLS)
    try:
        raw = _get(QUOTE_URL + symbols)
        for line in raw.strip().split(";"):
            line = line.strip()
            if "=" not in line or not line.startswith("v_"):
                continue
            payload = line.split("=", 1)[1].strip().strip('"')
            parts = payload.split("~")
            if len(parts) < 10:
                continue
            sym = line.split("=", 1)[0].removeprefix("v_")
            label = next((n for n, s in MACRO_SYMBOLS if s == sym), sym)
            items.append(
                {
                    "name": label,
                    "price": _parse_quote_field(parts, 3),
                    "pct": _parse_quote_field(parts, 32),
                }
            )
    except Exception:
        pass
    return items


def last_trade_date() -> str:
    """返回最近一个工作日（简化：跳过周末）。"""
    d = datetime.now() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def history_start(days_back: int = 400) -> str:
    return (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
