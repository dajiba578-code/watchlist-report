"""推送复盘报告到个人微信。

两种免费通道，配了哪个用哪个：
1. 企业微信群机器人 webhook（推荐，免费不限条数）
   微信里注册企业微信 -> 建群 -> 添加群机器人 -> 复制 webhook 地址
   环境变量: WECOM_WEBHOOK
2. Server酱（免费版每天 5 条，够用）
   到 sct.ftqq.com 用 GitHub 登录拿到 SendKey
   环境变量: SENDKEY

用法：
    python push_wechat.py --title "自选股复盘 08-13" --file wechat_summary.md
"""
from __future__ import annotations

import argparse
import os
import pathlib
import urllib.request
from datetime import datetime


def _post_json(url: str, payload: dict) -> str:
    data = json_dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def push_wecom(webhook: str, content: str) -> bool:
    """企业微信机器人 markdown 消息（上限 4096 字节）。"""
    if len(content.encode("utf-8")) > 4096:
        content = content[:1800] + "\n> 内容较长已截断，完整报告见网站"
    resp = _post_json(webhook, {"msgtype": "markdown", "markdown": {"content": content}})
    ok = '"errcode":0' in resp
    if not ok:
        print(f"企业微信推送返回: {resp}")
    return ok


def push_serverchan(sendkey: str, title: str, content: str) -> bool:
    """Server酱 Turbo：title + markdown 正文。"""
    import urllib.parse

    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    body = urllib.parse.urlencode(
        {"title": title, "desp": content.replace("\n", "\n\n")}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "Mozilla/5.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    ok = '"code":0' in text
    if not ok:
        print(f"Server酱推送返回: {text}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="wechat_summary.md")
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    project_dir = pathlib.Path(__file__).resolve().parent
    content = (project_dir / args.file).read_text(encoding="utf-8")
    title = args.title or f"自选股复盘 {datetime.now():%m-%d}"

    sent = 0
    wecom = os.environ.get("WECOM_WEBHOOK", "").strip()
    if wecom:
        sent += push_wecom(wecom, content)
    sendkey = os.environ.get("SENDKEY", "").strip()
    if sendkey:
        sent += push_serverchan(sendkey, title, content)
    if not sent:
        print("未配置推送通道（WECOM_WEBHOOK / SENDKEY），跳过推送。")
        print("摘要内容：\n" + content)


if __name__ == "__main__":
    main()
