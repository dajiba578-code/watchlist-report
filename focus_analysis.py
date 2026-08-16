"""每日焦点：从自选股中自动挑选信号最强的 3 只，生成 AI 深度分析。

挑股逻辑：TA 引擎信号权重（BUY=2 / HOLD=1 / SELL=0） + 四策略买入信号数×0.5 + TA 置信度。
分析生成：优先调用 DeepSeek LLM（环境变量 DEEPSEEK_API_KEY，OpenAI 兼容接口）；
未配置 key 时降级为规则模板分析（基于 TA 贡献 + 项目价位，0 成本）。
"""
from __future__ import annotations

import json
import os
import urllib.request

TA_WEIGHT = {"BUY": 2.0, "HOLD": 1.0, "SELL": 0.0}
ACTION_CN = {"BUY": "买入", "SELL": "卖出", "HOLD": "持有"}


def pick_focus(stocks: list[dict], n: int = 3) -> list[dict]:
    """按综合信号强度排序，挑出信号最强的 n 只。"""
    def score(s: dict) -> float:
        ta = s.get("ta") or {"action": "HOLD", "confidence": 0.0}
        return TA_WEIGHT.get(ta["action"], 1.0) * 2 + int(s.get("n_buy", 0)) * 0.5 + float(ta.get("confidence", 0))

    ranked = sorted(stocks, key=score, reverse=True)
    return ranked[:n]


def _template_analysis(s: dict) -> dict:
    """无 LLM 时的规则模板分析（基于 TA 贡献 + 项目价位）。"""
    ta = s.get("ta") or {"action": "HOLD", "confidence": 0.0, "contribs": []}
    bull = [c for c in ta.get("contribs", []) if c["direction"] == "bullish"]
    bear = [c for c in ta.get("contribs", []) if c["direction"] == "bearish"]
    bull_txt = "、".join(c["indicator"] for c in bull) or "无"
    bear_txt = "、".join(c["indicator"] for c in bear) or "无"
    near = "贴近20日支撑" if s.get("near_low") else "距支撑较远"
    pct5 = f"{s['pct5']:+.1f}%" if s.get("pct5") is not None else "—"
    analysis = (
        f"【技术面】TA 引擎 {ACTION_CN.get(ta['action'], ta['action'])}（置信度 {ta['confidence']:.2f}）："
        f"多头指标 {bull_txt}，空头指标 {bear_txt}；现价 {s['close']:.2f}，"
        f"MA20={s['ma20']:.2f}，MA60={s['ma60']:.2f}，RSI={s['rsi']:.1f}，{near}。\n"
        f"【资金面】近5日OBV方向已计入TA信号；近5日涨跌 {pct5}，今日 {s['pct']:+.2f}%。\n"
        f"【风险】ATR={s['atr']:.2f}，止损位 {s['stop']:.2f}（止损幅度约 {(s['close']/s['stop']-1)*100:.1f}%）。\n"
        f"【操作参考】建议买入区 {s['buy']:.2f} 附近分批，目标 {s['t1']:.2f}/{s['t2']:.2f}，止损 {s['stop']:.2f}。"
    )
    return {
        "code": s["code"], "name": s["name"], "market": s["market"],
        "action": ta["action"], "confidence": ta["confidence"],
        "rating": s["rating"], "close": s["close"], "pct": s["pct"],
        "buy": s["buy"], "t1": s["t1"], "t2": s["t2"], "stop": s["stop"],
        "rsi": s["rsi"], "atr": s["atr"], "ma20": s["ma20"], "ma60": s["ma60"],
        "analysis": analysis,
    }


def _llm_analysis(stocks: list[dict], api_key: str) -> list[dict] | None:
    """调用 DeepSeek 生成多空辩论式分析，失败返回 None（调用方降级模板）。"""
    items = []
    for s in stocks:
        ta = s.get("ta") or {"action": "HOLD", "confidence": 0.0, "contribs": []}
        contrib_txt = "；".join(
            f"{c['indicator']}:{c['direction']}({c['rationale']})" for c in ta.get("contribs", [])
        )
        items.append(
            f"- {s['name']}({s['code']}) 现价{s['close']:.2f} 今日{s['pct']:+.2f}% "
            f"RSI={s['rsi']:.1f} ATR={s['atr']:.2f} MA20={s['ma20']:.2f} MA60={s['ma60']:.2f} "
            f"20日支撑={s['support20']:.2f} 60日前高={s['resist60']:.2f} "
            f"四策略买入信号={s['n_buy']}/4 TA引擎={ta['action']}(conf {ta['confidence']:.2f}) "
            f"TA明细：{contrib_txt}"
        )
    sys_prompt = (
        "你是一名资深股票分析师，负责给自选股写每日复盘。对每只股票给出："
        "1) 技术面结论（趋势/动能/量能），2) 资金面，3) 牛方观点与熊方观点各一条，"
        "4) 风险提示，5) 操作参考（买入区间/目标价/止损价）。"
        "只输出一个 JSON 对象（不要输出数组），结构为："
        '{"stocks": [{"code": "代码", "name": "名称", "action": "BUY或SELL或HOLD", '
        '"confidence": 0-1之间数字, "bull": "牛方观点中文文本", "bear": "熊方观点中文文本", '
        '"risk": "风险提示中文文本", "advice": "操作参考中文文本"}]}。'
        "bull/bear/risk/advice 必须是详细的中文句子，不要用数字。每段不超过80字。"
    )
    user_prompt = "以下是最新交易日自选股技术数据（仅供参考，非实时）：\n" + "\n".join(items)
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("stocks") or [parsed]
    llm_map = {}
    for x in parsed:
        if isinstance(x, dict) and x.get("code"):
            for k in ("bull", "bear", "risk", "advice"):
                if not isinstance(x.get(k), str):
                    x[k] = str(x.get(k) or "")
            llm_map[x["code"]] = x
    out = []
    for s in stocks:
        x = llm_map.get(s["code"], {})
        analysis = (
            f"【技术面】{x.get('bull', '')}\n"
            f"【熊方观点】{x.get('bear', '')}\n"
            f"【风险】{x.get('risk', '')}\n"
            f"【操作参考】{x.get('advice', '')}"
        )
        out.append(_template_analysis(s) | {
            "action": x.get("action", s.get("ta", {}).get("action", "HOLD")),
            "confidence": float(x.get("confidence", s.get("ta", {}).get("confidence", 0))),
            "analysis": analysis,
            "llm": True,
        })
    return out


def build_focus(stocks: list[dict], api_key: str | None = None, n: int = 3) -> list[dict]:
    focus = pick_focus(stocks, n)
    if api_key:
        try:
            llm_out = _llm_analysis(focus, api_key)
            if llm_out:
                return llm_out
        except Exception as exc:
            print(f"LLM 分析失败，降级模板: {exc}")
    return [_template_analysis(s) for s in focus]
