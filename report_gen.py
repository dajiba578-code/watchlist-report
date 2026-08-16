"""生成「今日自选股复盘」报告：数据抓取 -> 四策略信号 -> 买卖建议 -> HTML + JSON + 微信摘要。

用法：
    python report_gen.py                # 生成今日报告
    python report_gen.py --date 2026-08-13   # 指定日期（用于补跑）
    python report_gen.py --no-push      # 只生成不推送
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime

import pandas as pd

import market_data as md
from recommendation import STRATEGY_KEYS, build_recommendation, price_levels

PROJECT_DIR = pathlib.Path(__file__).resolve().parent
SITE_DIR = PROJECT_DIR / "site"
REPORTS_DIR = SITE_DIR / "reports"

sys.path.insert(0, str(PROJECT_DIR))

from strategies.strategy_candlestick import compute_signals as candlestick_sig  # noqa: E402
from strategies.strategy_chanlun import compute_signals as chanlun_sig  # noqa: E402
from strategies.strategy_composite import compute_signals as composite_sig  # noqa: E402
from strategies.strategy_elliott_wave import compute_signals as wave_sig  # noqa: E402
from strategies.strategy_ta import aggregate_signals as ta_aggregate  # noqa: E402

STRATEGY_FUNCS = {
    "三维复合(趋势+回归+量价)": composite_sig,
    "K线形态(15种)": candlestick_sig,
    "缠论(分型笔中枢)": chanlun_sig,
    "波浪理论(ABC回调)": wave_sig,
}


def truncate_unfinished(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """盘中/盘后未稳定时截断当日未完成 bar，保证信号基于已收盘数据。

    A股：北京时间 15:30 前视为当日未收盘（含盘中 bar）；
    美股：美东时间 16:30 前视为当日未收盘（盘后未稳定）。
    """
    if len(df) < 2:
        return df
    last = df.index[-1]
    today = pd.Timestamp(datetime.now().date())
    if last.date() != today.date():
        return df
    now = datetime.now()
    if md.is_us(code):
        ny = md.ny_now()
        if ny.hour < 16 or (ny.hour == 16 and ny.minute < 30):
            return df.iloc[:-1]
    else:
        if now.hour < 15 or (now.hour == 15 and now.minute < 30):
            return df.iloc[:-1]
    return df


def load_watchlist() -> list[dict]:
    path = PROJECT_DIR / "watchlist.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少自选股配置: {path}")
    items = json.loads(path.read_text(encoding="utf-8"))
    seen = set()
    out = []
    for it in items:
        code = str(it.get("code", "")).strip().upper()
        if code and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": str(it.get("name", ""))})
    return out


def signal_state(series: pd.Series) -> int:
    return int(series.iloc[-1]) if len(series) else 0


def buy_sell_points(sig: pd.Series):
    """返回 [(日期, 价格, 'B'/'S'), ...]，基于持有状态跃迁。"""
    arr = sig.to_numpy()
    pts = []
    dates = sig.index
    for i in range(1, len(arr)):
        if arr[i] == 1 and arr[i - 1] == 0:
            pts.append((str(dates[i].date()), "B"))
        elif arr[i] == 0 and arr[i - 1] == 1:
            pts.append((str(dates[i].date()), "S"))
    return pts


def build_stock_item(code: str, name: str, df: pd.DataFrame, quote: dict | None) -> dict:
    sig_map: dict[str, int] = {}
    sig_pts: dict[str, list] = {}
    for label, fn in STRATEGY_FUNCS.items():
        try:
            s = fn(df)
            sig_map[label] = signal_state(s)
            sig_pts[label] = buy_sell_points(s)
        except Exception:
            sig_map[label] = 0
            sig_pts[label] = []
    n_buy = sum(sig_map.values())
    pl = price_levels(df)
    rec = build_recommendation(pl, n_buy, list(sig_map.values()))
    try:
        ta_action, ta_conf, ta_contribs = ta_aggregate(df)
        ta = {
            "action": ta_action,
            "confidence": round(ta_conf, 2),
            "contribs": [
                {"indicator": c.indicator, "direction": c.direction, "rationale": c.rationale}
                for c in ta_contribs
            ],
        }
    except Exception:
        ta = {"action": "HOLD", "confidence": 0.0, "contribs": [], "error": True}

    q = quote or {}
    price = q.get("price") or pl["close"]
    pct = q.get("pct")
    if pct is None and len(df) >= 2:
        pct = (pl["close"] / float(df["close"].iloc[-2]) - 1) * 100
    last = df.iloc[-1]
    chg5 = (
        (pl["close"] / float(df["close"].iloc[-6]) - 1) * 100 if len(df) >= 6 else None
    )

    return {
        "code": code,
        "name": name or q.get("name") or code,
        "market": "美股" if md.is_us(code) else "A股",
        "date": pl["last_date"],
        "close": round(float(price), 2),
        "pct": round(float(pct), 2) if pct is not None else None,
        "pct5": round(float(chg5), 2) if chg5 is not None else None,
        "open": round(float(last["open"]), 2),
        "high": round(float(last["high"]), 2),
        "low": round(float(last["low"]), 2),
        "pe": round(q["pe"], 2) if q.get("pe") else None,
        "mcap": q.get("mcap"),
        "n_buy": n_buy,
        "signals": sig_map,
        "ta": ta,
        "rating": rec["rating"],
        "buy": rec["buy"],
        "t1": rec["t1"],
        "t2": rec["t2"],
        "stop": rec["stop"],
        "chosen": rec["chosen"],
        "rsi": round(pl["rsi14"], 1),
        "atr": round(pl["atr"], 2),
        "ma20": round(pl["ma20"], 2),
        "ma60": round(pl["ma60"], 2),
        "support20": round(pl["support20"], 2),
        "resist60": round(pl["resist60"], 2),
        "near_low": (pl["close"] - pl["support20"]) <= 0.5 * pl["atr"],
        "kline": [
            [str(d.date()), o, c, l, h, v]
            for d, o, c, l, h, v in zip(
                df.index[-120:],
                df["open"].iloc[-120:],
                df["close"].iloc[-120:],
                df["low"].iloc[-120:],
                df["high"].iloc[-120:],
                df["volume"].iloc[-120:],
            )
        ],
        "ma20_hist": [round(x, 2) for x in df["close"].rolling(20).mean().iloc[-120:].tolist()],
        "ma60_hist": [round(x, 2) for x in df["close"].rolling(60).mean().iloc[-120:].tolist()],
        "sig_points": sig_pts,
    }


def build_report(date_str: str) -> dict:
    watchlist = load_watchlist()
    codes = [it["code"] for it in watchlist]
    start = md.history_start(400)
    end = date_str if date_str else datetime.now().strftime("%Y-%m-%d")

    quotes = md.fetch_quotes(codes)
    macro = md.fetch_macro()

    stocks = []
    errors = []
    for it in watchlist:
        try:
            df = md.fetch_daily(it["code"], start, end)
            df = truncate_unfinished(df, it["code"])
            stocks.append(build_stock_item(it["code"], it["name"], df, quotes.get(it["code"])))
        except Exception as exc:
            errors.append(f"{it['code']}: {exc}")

    stocks.sort(key=lambda s: (s["market"] != "A股", s["code"]))
    up = sum(1 for s in stocks if (s["pct"] or 0) > 0)
    down = sum(1 for s in stocks if (s["pct"] or 0) < 0)
    active = [s for s in stocks if s["rating"] == "积极关注"]
    watch = [s for s in stocks if s["rating"] == "观望"]

    report_date = max((s["date"] for s in stocks), default=datetime.now().strftime("%Y-%m-%d"))
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_date": report_date,
        "macro": macro,
        "summary": {
            "total": len(stocks),
            "up": up,
            "down": down,
            "active": [s["code"] for s in active],
            "watch": [s["code"] for s in watch],
            "errors": errors,
        },
        "stocks": stocks,
    }


def render_html(report: dict) -> str:
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    date = report["report_date"]
    up, down = report["summary"]["up"], report["summary"]["down"]
    macro_html = "".join(
        f'<span class="idx">{m["name"]} <b>{m["price"]:.2f}</b> '
        f'<em class="{"up" if (m["pct"] or 0) >= 0 else "down"}">{m["pct"]:+.2f}%</em></span>'
        for m in report["macro"]
    )
    rows = []
    for s in report["stocks"]:
        sig_html = " ".join(
            f'<span class="tag {"on" if v else ""}" title="{k}">{k.split("(")[0]}</span>'
            for k, v in s["signals"].items()
        )
        ta = s.get("ta") or {"action": "HOLD", "confidence": 0.0, "contribs": []}
        ta_cls = {"BUY": "on", "SELL": "sell", "HOLD": ""}.get(ta["action"], "")
        ta_label = f'<span class="tag ta {ta_cls}" title="TradingAgents 信号引擎">TA {ta["action"]} {ta["confidence"]:.2f}</span>'
        ta_reasons = " · ".join(
            f'{c["indicator"]}:{c["direction"]}' for c in ta.get("contribs", [])
        ) or "信号不足"
        ta_line = (
            f'<div class="ta-line">TA 引擎：{ta["action"]}（置信度 {ta["confidence"]:.2f}）'
            f"&nbsp;·&nbsp;{ta_reasons}</div>"
        )
        pct_cls = "up" if (s["pct"] or 0) >= 0 else "down"
        rows.append(
            "<details class='stock-card' data-code='{}'>".format(s["code"])
            + "<summary>"
            + f'<span class="name">{s["name"]}</span>'
            + f'<span class="code">{s["code"]} · {s["market"]}</span>'
            + f'<span class="close">{s["close"]:.2f}</span>'
            + f'<span class="pct {pct_cls}">{s["pct"]:+.2f}%</span>'
            + f'<span class="rating {s["rating"]}">{s["rating"]}</span>'
            + f'<span class="nbuy">买入信号 {s["n_buy"]}/4</span>'
            + "</summary>"
            + "<div class='body'>"
            + f'<div class="signals">{sig_html}{ta_label}</div>'
            + f'<table class="levels"><tr><th>建议买入</th><th>目标价1</th><th>目标价2</th><th>止损价</th>'
            + f'<th>RSI</th><th>ATR</th><th>MA20</th><th>MA60</th><th>20日支撑</th><th>60日前高</th></tr>'
            + f'<tr><td class="buy">{s["buy"]:.2f}</td><td>{s["t1"]:.2f}</td><td>{s["t2"]:.2f}</td>'
            + f'<td class="stop">{s["stop"]:.2f}</td><td>{s["rsi"]:.1f}</td><td>{s["atr"]:.2f}</td>'
            + f'<td>{s["ma20"]:.2f}</td><td>{s["ma60"]:.2f}</td><td>{s["support20"]:.2f}</td>'
            + f'<td>{s["resist60"]:.2f}</td></tr></table>'
            + ta_line
            + f'<div class="kline" style="height:320px"></div>'
            + "</div></details>"
        )
    stock_rows = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>自选股复盘 {date}</title>
<link rel="stylesheet" href="../assets/style.css">
<script src="../assets/echarts.min.js"></script>
</head>
<body>
<header>
  <h1>自选股复盘报告 <small>{date}</small></h1>
  <div class="meta">生成时间 {report['generated_at']} · 数据源：腾讯/新浪（免费，国内直连）</div>
  <div class="macro">{macro_html}</div>
  <div class="summary-line">共 {report['summary']['total']} 只自选股，今日 <b class="up">{up} 涨</b> / <b class="down">{down} 跌</b>
  · 积极关注 {len(report['summary']['active'])} 只</div>
</header>
<main>{stock_rows}</main>
<footer>本报告由量化策略自动生成，仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。</footer>
<script>
const DATA = {payload};
document.querySelectorAll('.stock-card').forEach(card => {{
  const code = card.dataset.code;
  const stock = DATA.stocks.find(s => s.code === code);
  if (!stock) return;
  const el = card.querySelector('.kline');
  const dates = stock.kline.map(k => k[0]);
  const ohlc = stock.kline.map(k => [k[1], k[2], k[3], k[4]]);
  const vols = stock.kline.map(k => k[5]);
  const markData = [];
  ['三维复合(趋势+回归+量价)','K线形态(15种)','缠论(分型笔中枢)','波浪理论(ABC回调)'].forEach(skey => {{
    (stock.sig_points[skey] || []).forEach(p => {{
      const idx = dates.indexOf(p[0]);
      if (idx < 0) return;
      markData.push({{ coord: [idx, stock.kline[idx][2]], value: p[1], itemStyle: {{ color: p[1]==='B' ? '#ff4d6d' : '#00d68f' }} }});
    }});
  }});
  const chart = echarts.init(el);
  chart.setOption({{
    animation: false,
    backgroundColor: '#0d1117',
    grid: [{{ left: 50, right: 12, top: 20, height: '62%' }}, {{ left: 50, right: 12, top: '78%', height: '16%' }}],
    xAxis: [
      {{ type: 'category', data: dates, boundaryGap: true, axisLine: {{ lineStyle: {{ color: '#333' }} }}, axisLabel: {{ color: '#888' }} }},
      {{ type: 'category', gridIndex: 1, data: dates, axisLabel: {{ show: false }}, axisLine: {{ lineStyle: {{ color: '#333' }} }} }}
    ],
    yAxis: [
      {{ scale: true, axisLabel: {{ color: '#888' }}, splitLine: {{ lineStyle: {{ color: '#1e2733' }} }} }},
      {{ gridIndex: 1, scale: true, axisLabel: {{ show: false }}, splitLine: {{ show: false }} }}
    ],
    dataZoom: [{{ type: 'inside', xAxisIndex: [0,1], start: Math.max(0, 100 - 9000/dates.length), end: 100 }}],
    series: [
      {{ type: 'candlestick', data: ohlc, itemStyle: {{ color: '#ff4d6d', color0: '#00d68f', borderColor: '#ff4d6d', borderColor0: '#00d68f' }}, markPoint: {{ data: markData, symbol: 'pin', symbolSize: 42, label: {{ color: '#fff', fontSize: 10 }} }} }},
      {{ type: 'line', data: stock.ma20_hist, showSymbol: false, lineStyle: {{ color: '#f5a623', width: 1 }} }},
      {{ type: 'line', data: stock.ma60_hist, showSymbol: false, lineStyle: {{ color: '#4dabf7', width: 1 }} }},
      {{ type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, itemStyle: {{ color: 'rgba(80,160,255,0.35)' }} }}
    ],
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }}, backgroundColor: '#161b22', borderColor: '#30363d', textStyle: {{ color: '#ddd' }} }}
  }});
  card.querySelector('summary').addEventListener('click', () => setTimeout(() => chart.resize(), 50));
}});
</script>
</body>
</html>"""


def render_index(reports_meta: list[dict]) -> str:
    payload = json.dumps({"reports": reports_meta}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>自选股复盘 · 历史报告</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
  <h1>自选股智能复盘</h1>
  <div class="meta">每天收盘后自动生成 · 免费行情源 · 量化策略仅供参考</div>
</header>
<main id="list"></main>
<footer>本网站由量化策略自动生成报告，仅供参考，不构成任何投资建议。</footer>
<script>
fetch('reports/index.json').then(r => r.json()).then(data => {{
  const list = document.getElementById('list');
  if (!data.reports || !data.reports.length) {{
    list.innerHTML = '<div class="empty">暂无报告，等待第一次自动运行。</div>';
    return;
  }}
  data.reports.forEach(r => {{
    const a = document.createElement('a');
    a.className = 'report-link';
    a.href = 'reports/' + r.file;
    a.innerHTML = '<span class="d">' + r.date + '</span>' +
      '<span class="s">' + r.summary + '</span>' +
      '<span class="g">' + r.generated + '</span>';
    list.appendChild(a);
  }});
}});
</script>
</body>
</html>"""


def write_wechat_summary(report: dict) -> str:
    """生成微信推送摘要（企业微信 markdown 格式）。"""
    d = report["report_date"]
    m = report["summary"]
    lines = [f"## 📊 自选股复盘 {d}", ""]
    idxs = " ".join(f"{x['name']}{x['price']:.0f}({x['pct']:+.1f}%)" for x in report["macro"][:4])
    if idxs:
        lines.append(f"**大盘**：{idxs}")
    lines.append(f"**自选股**：{m['total']} 只 · {m['up']}涨 {m['down']}跌")
    lines.append("")
    lines.append("### 积极关注")
    act = [s for s in report["stocks"] if s["rating"] == "积极关注"]
    if act:
        for s in act:
            ta_mark = {"BUY": " 🔺TA买", "SELL": " 🔻TA卖"}.get(s["ta"]["action"], "")
            lines.append(
                f"- **{s['name']}**({s['code']}) 现价 {s['close']:.2f} ({s['pct']:+.2f}%) ｜ "
                f"建议买入 {s['buy']:.2f} ｜ 目标 {s['t1']:.2f}/{s['t2']:.2f} ｜ 止损 {s['stop']:.2f}{ta_mark}"
            )
    else:
        lines.append("- 今日无积极关注标的")
    lines.append("")
    lines.append("### 关注")
    foc = [s for s in report["stocks"] if s["rating"] == "关注"]
    if foc:
        for s in foc:
            ta_mark = {"BUY": " 🔺TA买", "SELL": " 🔻TA卖"}.get(s["ta"]["action"], "")
            lines.append(
                f"- {s['name']}({s['code']}) {s['close']:.2f} ({s['pct']:+.2f}%) 买入 {s['buy']:.2f} 目标 {s['t1']:.2f}{ta_mark}"
            )
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("### 观望")
    wat = [s for s in report["stocks"] if s["rating"] == "观望"]
    lines.append("- " + "、".join(f"{s['name']}({s['code']})" for s in wat[:8]) if wat else "- 无")
    lines.append("")
    lines.append("[查看完整报告与K线](https://dajiba578-code.github.io/watchlist-report/)")
    lines.append("> 仅供量化研究参考，不构成投资建议")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(args.date)
    date = report["report_date"]

    html = render_html(report)
    (REPORTS_DIR / f"{date}.html").write_text(html, encoding="utf-8")
    (REPORTS_DIR / f"{date}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    index_path = REPORTS_DIR / "index.json"
    prev = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"reports": []}
    meta = {
        "date": date,
        "file": f"{date}.html",
        "generated": report["generated_at"],
        "summary": f"{report['summary']['total']}只 · {report['summary']['up']}涨{report['summary']['down']}跌 · 积极关注{len(report['summary']['active'])}",
    }
    prev["reports"] = [
        r for r in prev.get("reports", [])
        if r["date"] != date and (REPORTS_DIR / r.get("file", "")).exists()
    ]
    prev["reports"].insert(0, meta)
    prev["reports"] = prev["reports"][:90]
    (REPORTS_DIR / "index.json").write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE_DIR / "index.html").write_text(render_index(prev["reports"]), encoding="utf-8")

    summary = write_wechat_summary(report)
    (PROJECT_DIR / "wechat_summary.md").write_text(summary, encoding="utf-8")

    print(f"报告已生成: {REPORTS_DIR / (date + '.html')}")
    print(f"自选股 {report['summary']['total']} 只，{report['summary']['up']} 涨 {report['summary']['down']} 跌，"
          f"积极关注 {len(report['summary']['active'])} 只")
    for e in report["summary"]["errors"]:
        print(f"  警告: {e}")


if __name__ == "__main__":
    main()
