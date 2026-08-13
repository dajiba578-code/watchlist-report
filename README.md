# 自选股智能复盘 · 免费网站 + 微信推送

每天收盘后自动生成「今日自选股复盘报告」，推送到你的个人微信，并在免费网站上存档（含 K 线图和历史报告）。

**运行成本：0 元/月**。用到的全部是免费服务：

| 服务 | 用途 | 费用 |
|------|------|------|
| GitHub Pages | 网站托管 | 免费 |
| GitHub Actions | 每天定时自动生成报告 | 免费（每月 2000 分钟额度，用不到 5%） |
| 东方财富/腾讯/新浪 | 行情数据（A股+美股，国内直连，不用翻墙） | 免费 |
| 企业微信 或 Server酱 | 推送到个人微信 | 免费 |

策略引擎与桌面 EXE 完全同源：四策略（三维复合、K线形态、缠论、波浪理论）+ 建议买入/目标价/止损，来自 vibe-trading skill。

---

## 目录结构

```
watchlist-report/
├── watchlist.json        # 自选股配置（改这里换成你的股票）
├── market_data.py        # 免费行情抓取（东财主 + 腾讯/新浪备用）
├── strategies/           # 四策略信号引擎（与桌面 EXE 同源）
├── recommendation.py     # 建议买入/目标价/止损口径（与 EXE 一致）
├── report_gen.py         # 报告生成器（HTML + JSON + 微信摘要）
├── push_wechat.py        # 企业微信 / Server酱 推送
├── site/                 # 网站文件（GitHub Pages 部署）
│   ├── index.html        # 历史报告列表
│   ├── assets/           # 样式 + ECharts（本地文件，不依赖 CDN）
│   └── reports/          # 每日报告（自动生成）
└── .github/workflows/    # 每天自动运行的任务
```

## 一、本地先跑通（可选，30 秒）

```bash
pip install -r requirements.txt
python report_gen.py        # 生成今日报告到 site/reports/
python push_wechat.py       # 没配推送时会打印摘要内容
```

用浏览器打开 `site/index.html` 即可看到报告列表，点击进入单日报告查看 K 线和买卖点。

## 二、部署到 GitHub（免费，约 20 分钟）

### 1. 注册 GitHub 并新建仓库

1. 到 [github.com](https://github.com) 注册账号（免费）。
2. 点右上角 **+ → New repository**，仓库名填 `watchlist-report`，选 **Private**（私人仓库，别人看不到），创建。

### 2. 把代码推上去

在本地项目目录打开命令行：

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/watchlist-report.git
git push -u origin main
```

### 3. 配置微信推送（二选一）

**方式 A：企业微信群机器人（推荐，免费不限条数）**

1. 手机下载「企业微信」App，注册（个人即可，免费）。
2. 在电脑端企业微信里：**消息 → 右上角 + → 发起群聊**，拉你自己（或拉个朋友再退出）建一个群。
3. 群里点 **群设置 → 群机器人 → 添加机器人**，复制 webhook 地址（形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx`）。
4. 微信会同步收到企业微信消息（企业微信和微信已打通）。

**方式 B：Server酱（免费版每天 5 条）**

1. 打开 [sct.ftqq.com](https://sct.ftqq.com)，用 GitHub 登录。
2. 复制页面上的 SendKey。

然后把密钥配到 GitHub 仓库（**Settings → Secrets and variables → Actions → New repository secret**）：

| Secret 名 | 填什么 |
|-----------|--------|
| `WECOM_WEBHOOK` | 企业微信机器人 webhook 地址（方式 A） |
| `SENDKEY` | Server酱 SendKey（方式 B） |

两个都配也可以，会同时推送。

### 4. 开启 GitHub Pages

仓库 **Settings → Pages**：

- Source 选 **GitHub Actions**（不是 Deploy from a branch）。

### 5. 修改自选股

编辑 `watchlist.json`，改成你的股票：

```json
[
  { "code": "600519.SH", "name": "贵州茅台" },
  { "code": "300750.SZ", "name": "宁德时代" },
  { "code": "AAPL.US", "name": "苹果" },
  { "code": "TSLA.US", "name": "特斯拉" }
]
```

- A股：6 位代码 + `.SH` / `.SZ`（如 `000858.SZ`）
- 美股：代码 + `.US`（如 `NVDA.US`、`BRK.B` 用 `BRK-B.US`）

改完 `git add watchlist.json && git commit -m "update watchlist" && git push`。

### 6. 首次手动运行 + 验证

仓库 **Actions → daily-watchlist-report → Run workflow**，等 1-2 分钟跑完：

- 微信会收到复盘摘要（如果配了推送）
- 网站地址：`https://你的用户名.github.io/watchlist-report/`

之后完全自动：

| 时间（北京时间） | 做什么 |
|------------------|--------|
| 周一至周五 15:40 | A股收盘后生成当日复盘 |
| 周二至周六 06:40 | 美股收盘后更新美股数据 |

## 三、报告里有什么

每份报告包含：

- **大盘速览**：上证/深成/创业板 + 道指/纳指/标普/VIX
- **自选股总览**：今日涨跌家数、积极关注/关注/观望
- **个股卡片**：收盘、涨跌幅、四策略信号（三维复合/K线/缠论/波浪）、评级、
  建议买入价、目标价1/2、止损价、RSI/ATR/支撑压力
- **K 线图**：近 120 根日K + MA20/MA60 + 成交量，图上标注四策略的买卖点

评级口径与桌面 EXE 一致：四策略买入信号 ≥2 积极关注 / 1 关注 / 0 观望。

## 四、常见问题

**Q：不想用 GitHub，只想本地跑？**
Windows 任务计划程序每天定时执行 `python report_gen.py` 即可，推送照常用。

**Q：想早上也推一次（A股盘前）？**
在 `daily-report.yml` 的 `schedule` 里加一行 cron 就行，比如早上 8:40 加推一次美股隔夜复盘。

**Q：报告数据是哪天的？**
盘中运行会截断到最近已收盘交易日（避免把盘中未完成的价格当收盘价）；收盘后运行就是当天。

**Q：网站国内访问慢？**
GitHub Pages 在国内一般可访问，偶发慢。可以再花 0 元接 Cloudflare Pages 做镜像，或以后买域名加速。

## 免责声明

本项目的报告由量化策略自动生成，仅供技术研究与学习参考，不构成任何投资建议。历史回测不代表未来收益，买卖价格仅为技术位参考，请结合基本面与个人风险承受能力独立决策。股市有风险，投资需谨慎。
