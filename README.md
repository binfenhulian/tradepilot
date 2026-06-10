# 📈 TradePilot

> A **chat-room–style, multi-LLM stock decision-assist** toy: throw in a question, watch a 🐂 **Bull** and a 🐻 **Bear** debate over the *same real market facts*, and get a **decisive call** from a ⚖️ **Portfolio Manager**.
>
> Inspired by — and a deliberate homage to — [**TradingAgents**](https://github.com/TauricResearch/TradingAgents). TradePilot keeps its best idea (multi-agent debate over shared, tool-fetched facts) and strips everything else down to a single zero-dependency Python file you can run in 10 seconds.

> ⚠️ **For learning & fun only. This is NOT financial advice.** Do not trade real money based on its output.

---

## Why this exists

[TradingAgents](https://github.com/TauricResearch/TradingAgents) is a brilliant multi-agent LLM trading framework that mirrors a real trading firm: analyst teams, bull/bear researchers, a trader, a risk team, and a portfolio manager — all debating to a decision. It's powerful, but it's a *research framework*.

I wanted the **core insight** in the simplest possible form, as a thing I'd actually open every day:

- **Multi-agent debate beats one oracle.** Opposing views (bull vs bear) surface risks a single "what should I do?" prompt never would.
- **Feed models the same hard facts, don't let them browse.** Quant data (price, RSI/MACD, news) is fetched once by the backend and injected identically to every agent — so the debate is fair and grounded, not built on each model's flaky, divergent web search.
- **End with a decision.** A Portfolio Manager reads the debate and gives one clear, executable call — entry/exit levels, sizing, triggers.

TradePilot is that, as a chat room with a live portfolio dashboard. Two models (e.g. **Gemini** + **DeepSeek**) play the roles; you just ask.

## What it does

Ask things like *"Should I do anything with my MU right now?"* or *"Why is GOOGL down today?"* and:

- 🧠 **AI routes your intent** (no keywords — a model decides):
  - **Decision** ("should I buy/sell/hold?") → 🐂 Bull → 🐻 Bear → ⚖️ Portfolio Manager verdict
  - **Analysis** ("why did it move? what's the read?") → a single 🔍 Analyst answers directly
  - **Chit-chat** (off-topic) → politely declined, no data fetched, no tokens wasted
- 📊 **Live portfolio dashboard** — add/edit/delete your own holdings, real-time-ish quotes via Yahoo Finance, today's P&L, total P&L, sparklines, and a US-market-session badge (pre / regular / post / closed) computed from Eastern time.
- 🧾 **Shared facts, injected not searched** — price, prev close, day range, 52-week range, SMA/EMA/RSI/MACD, **and recent news headlines** are pulled by the backend and given to every agent as one ground-truth card.
- 🎛️ **Roles ↔ models are configurable** from the UI — pick which model plays Bull / Bear / Judge; they can even all be the same model. Changes apply instantly, no restart.
- 🧭 **Long-term–aware judge** — tell it your horizon in your profile (e.g. *"long-term bullish on semis/AI"*) and the Portfolio Manager won't flip-flop on daily noise: it's fed **summaries of its own past verdicts on that ticker** and asked to stay consistent unless the long-term thesis actually breaks. (Bull & Bear stay purely objective.)
- 📜 **Every debate is logged** (prompts, injected data, news, each role's output, latency) to `logs/`, and you can **replay any past debate** in the UI — with collapsible "see the exact prompts & data" panels for tuning.
- 🪶 **Zero dependencies.** Pure Python standard library (`urllib` + `http.server`). No `pip install`, no SDKs. Just `python3 server.py`.

## Design choice: fetch data yourself vs. let models search

A core decision — and TradePilot takes the same stance as TradingAgents:

| | Self-fetch & inject (what we do) | Let each model web-search |
|---|---|---|
| **Consistency** | ✅ all models see identical numbers → fair debate | ❌ models find different prices → talking past each other |
| **Accuracy** | ✅ real quote, indicators computed in code | ❌ LLMs hallucinate prices, miscompute indicators |
| **Capability parity** | ✅ independent of each model | ❌ uneven (some models have grounding, some don't) |

So **quantitative facts and news are fetched once and shared**. Models only interpret. (For true tick-by-tick real-time you'd plug in a streaming quote provider — see Roadmap.)

## Architecture

```
market.py    Quotes + technical indicators (Yahoo Finance via urllib, pure-Python SMA/RSI/MACD)
news.py      News headlines (Yahoo search endpoint; parsing adapted from TradingAgents)
llm.py       LLM clients for Gemini + DeepSeek (raw REST, no SDK)
config.py    Role→model mapping, API keys from env, role config persistence
storage.py   Holdings + investment-profile read/write
debate.py    Orchestration: intent routing → Bull→Bear→Judge / Analyst / decline
logbook.py   Per-debate JSON logs + history index + past-verdict summaries
server.py    HTTP server: REST API + SSE streaming + static hosting
static/      Frontend: chat room + portfolio dashboard (vanilla JS, canvas sparklines)
```

## Quick start

```bash
# 1. Configure API keys
cp .env.example .env
#   then edit .env and set GEMINI_API_KEY and DEEPSEEK_API_KEY

# 2. (optional) seed example holdings
cp data/holdings.example.json data/holdings.json

# 3. Run — zero dependencies, just the system python3
python3 server.py        # or ./run.sh

# 4. Open
#    http://localhost:8000
```

You get a free Gemini key at [aistudio.google.com](https://aistudio.google.com) and a DeepSeek key at [platform.deepseek.com](https://platform.deepseek.com).

## Configuration

**Models & roles** live in `config.json`. Define model aliases under `models`, then assign roles:

```json
{
  "models": {
    "gemini":   { "provider": "gemini",   "model": "gemini-3.5-flash",   "temperature": 0.7 },
    "deepseek": { "provider": "deepseek", "model": "deepseek-v4-flash",  "temperature": 0.7 }
  },
  "roles": { "bull": "gemini", "bear": "deepseek", "judge": "gemini" }
}
```

- Put **any model id your account can call** in `model` (the file lists current Gemini / DeepSeek ids in a comment block).
- Edit `roles` (or use the ⚙️ picker in the chat room) to reassign who plays each role — effective immediately.
- The **intent router** reuses the `judge` model automatically.

**Your profile** (investment preferences / horizon) is editable in the left panel and injected into the agents — this is where you state your long-term thesis.

## Logging & replay

Each debate writes `logs/<timestamp>_<ticker>_<intent>.json` containing the intent decision, the injected market/news/holding/preference context, and every role's system prompt, user prompt, model, output, and latency. The 📜 button in the chat room lists and replays past debates, with expandable prompt/data panels — built for tuning.

## Roadmap ideas

- Pre/post-market **prices** (the free Yahoo endpoint gives session state reliably but not always the extended price — a provider like Finnhub would fill this).
- True real-time via a streaming quote WebSocket (Finnhub / Polygon / Alpaca).
- Optional news web-search as a *supplementary* qualitative tool.

## Credits

- 🙏 **[TradingAgents](https://github.com/TauricResearch/TradingAgents)** by [Tauric Research](https://github.com/TauricResearch) — the multi-agent-debate philosophy this project is built on. Go star it; it's the real deal.
- Quotes & news: Yahoo Finance public endpoints. LLMs: Google Gemini, DeepSeek.

## License

MIT — see [LICENSE](LICENSE).

---
---

# 中文说明

> **聊天室形式的多模型股票决策辅助玩具**：抛个议题，看 🐂 多头 与 🐻 空头 基于*同一份真实行情*辩论，最后由 ⚖️ 组合经理给出**确定性操作建议**。
>
> 致敬 [**TradingAgents**](https://github.com/TauricResearch/TradingAgents)：保留它最精髓的「多智能体辩论 + 统一喂事实」，砍掉其余一切，做成一个零依赖、10 秒能跑起来的小工具。

> ⚠️ **仅供学习娱乐，不构成任何投资建议。** 别拿真金白银照着操作。

## 核心理念

[TradingAgents](https://github.com/TauricResearch/TradingAgents) 是一套出色的多智能体交易框架，模拟真实交易公司（分析师团队、多空研究员、交易员、风控、组合经理）辩论出决策。它很强，但它是个*研究框架*。我想要它的**核心思想 + 最简形态**：

- **多智能体辩论 > 单一神谕**：多空对立能逼出单条「我该怎么办」永远问不出来的风险。
- **喂同一份硬事实，别让模型自己上网搜**：行情/指标/新闻由后端拉一次、原样发给每个智能体——辩论才公平、才落地，而不是建立在各模型参差不齐、各搜各的结果上。
- **必须给出决策**：组合经理读完辩论，给一条明确、可执行的结论（建仓/止盈/止损价位、仓位、触发条件）。

## 主要功能

- 🧠 **AI 自动判别意图**（不靠关键词，由模型判断）：决策类→多空辩论+裁决；解读类→单个分析师直接答；无关闲聊→礼貌挡回、不查数据不浪费 token。
- 📊 **实时持仓看板**：自己增删改持仓、Yahoo 实时报价、今日/总盈亏、迷你走势、美股时段标签（盘前/盘中/盘后/休市，按美东时间自算）。
- 🧾 **统一事实注入**：价格、涨跌、区间、SMA/EMA/RSI/MACD **+ 近期新闻**由后端拉好，作为同一张「事实卡」发给所有角色。
- 🎛️ **角色↔模型可配置**：界面里选谁演多头/空头/裁判，可三个都用同一模型，改完即时生效。
- 🧭 **长线友好的裁判**：把你的长期立场写进偏好（如「长期看好半导体/AI」），裁判会被喂入**它对该标的过往裁决的摘要**，要求长期逻辑没实质变化就别被日内噪音带着天天翻烧饼（多空仍保持客观）。
- 📜 **每场辩论留日志**（提示词/注入数据/新闻/各角色输出/耗时）落 `logs/`，界面可回放任意历史场次，并展开看当时确切的提示词与数据，方便调优。
- 🪶 **零依赖**：纯 Python 标准库，`python3 server.py` 直接跑。

## 快速开始

```bash
cp .env.example .env        # 填入 GEMINI_API_KEY 和 DEEPSEEK_API_KEY
cp data/holdings.example.json data/holdings.json   # 可选：示例持仓
python3 server.py           # 然后打开 http://localhost:8000
```

## 致敬

🙏 **[TradingAgents](https://github.com/TauricResearch/TradingAgents)**（[Tauric Research](https://github.com/TauricResearch)）—— 本项目的多智能体辩论思想源自于此，强烈推荐去给它点个 star。
