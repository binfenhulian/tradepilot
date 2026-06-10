"""会话编排：先由 AI 判断议题意图，再路由到不同流程。

- DECISION（决策类）→ 多头 → 空头 → 裁判（组合经理），参考 TradingAgents 的多空辩论 + 拍板
- ANALYSIS（解读/原因/科普类）→ 单个分析师直接回答
- CHITCHAT（无关闲聊）→ 礼貌挡回，不查数据、不走流程

DECISION / ANALYSIS 都共享同一份「行情事实卡片 + 近期新闻 + 持仓 + 投资偏好」。
run_debate 是生成器，逐角色 yield 结果，便于 SSE 流式推送。
"""

import time

import market
import news
import storage
import llm
import config
import logbook


ROLE_META = {
    "bull": {"name": "多头研究员", "avatar": "🐂"},
    "bear": {"name": "空头研究员", "avatar": "🐻"},
    "judge": {"name": "组合经理", "avatar": "⚖️"},
    "analyst": {"name": "分析师", "avatar": "🔍"},
    "host": {"name": "主持人", "avatar": "💬"},
}


def _holding_context(ticker, quote):
    """根据持仓表算出该标的的持仓与浮动盈亏文本。"""
    ticker = ticker.upper()
    for h in storage.list_holdings():
        if h["ticker"] == ticker:
            shares = h["shares"]
            cost = h["cost"]
            price = quote.get("price") or 0
            mv = shares * price
            pnl = (price - cost) * shares
            pnl_pct = (price - cost) / cost * 100 if cost else 0
            return (
                f"你当前持有 {ticker}：{shares} 股，成本价 {cost}，"
                f"现价 {price}，市值 {round(mv, 2)}，"
                f"浮动盈亏 {round(pnl, 2)}（{round(pnl_pct, 2)}%）。"
            )
    return f"你目前没有持有 {ticker}（属于是否建仓的问题）。"


def _build_shared(topic, ticker):
    mc = market.build_market_context(ticker)
    holding = _holding_context(ticker, mc["quote"])
    prefs = storage.get_profile().get("preferences", "")
    try:
        news_text = news.build_news_context(ticker)
    except Exception:
        news_text = ""  # 新闻拉取失败不影响辩论
    news_block = f"\n【近期相关新闻（所有人共享，仅供参考，请勿臆造）】\n{news_text}\n" if news_text else ""
    shared = (
        f"【议题】{topic}\n\n"
        f"【实时行情事实（所有人共享，请以此为准，不要臆造价格）】\n{mc['text']}\n"
        f"{news_block}\n"
        f"【我的持仓情况】\n{holding}\n\n"
        f"【我的投资偏好】\n{prefs}\n"
    )
    pieces = {"market": mc["text"], "news": news_text, "holding": holding, "preferences": prefs}
    return shared, mc, pieces


_BULL_SYS = (
    "你是一名偏激进的【多头研究员】，在一个投资学习聊天室里。"
    "你的任务是基于给定的实时行情事实，为这个标的找出尽可能有说服力的【看多/买入/持有】理由："
    "技术面支撑、趋势动能、估值修复空间、催化剂等。"
    "要结合用户的持仓和投资偏好给出具体观点。"
    "用中文，markdown 分点，控制在 250 字内，观点鲜明但必须基于给定数据，不要编造价格或财报数字。"
)

_BEAR_SYS = (
    "你是一名偏保守的【空头研究员】，在一个投资学习聊天室里。"
    "你刚听完多头的发言，你的任务是基于实时行情事实，指出风险与【看空/谨慎/减仓/不建仓】的理由："
    "技术面压力位、超买、回调风险、估值偏高、宏观或基本面隐患等，"
    "并可直接反驳多头观点中站不住脚的地方。"
    "结合用户持仓和偏好。用中文，markdown 分点，控制在 250 字内，必须基于给定数据，不要编造。"
)

_JUDGE_SYS = (
    "你是经验丰富的【组合经理】，是这个聊天室里做最终决策的人。"
    "用户是投资小白，没有自己判断的能力，需要你给一个【明确、确定性】的操作建议——不要模棱两可。"
    "你已经看了多头和空头的辩论，以及实时行情事实、用户持仓和投资偏好。"
    "【特别重要】认真对待用户的投资期限与长期立场：若用户表明是长期持有者、且其长期逻辑"
    "（例如长期看好半导体/AI）没有被实质破坏，你的默认结论就应该是「继续持有 / 无需操作」，"
    "不要因为日内技术指标（RSI/MACD）或单日新闻这类短期噪音就频繁改变操作方向；"
    "只有当长期逻辑或基本面出现实质变化、或估值出现极端时，才建议调整仓位。"
    "如果下面给出了【过往结论摘要】，请与之保持连贯，若要改变立场必须明确说明发生了什么实质变化。\n\n"
    "请综合双方观点，给出你的最终裁决。严格按以下 markdown 结构输出（用中文）：\n\n"
    "## ⚖️ 最终裁决\n"
    "**操作建议**：（从 买入/加仓/持有/减仓/卖出/观望 中明确选一个）\n"
    "**建议价位**：（具体的建仓/加仓/止盈/止损价位或区间）\n"
    "**建议仓位**：（结合用户偏好给出占比或股数级别建议）\n"
    "**核心理由**：（2-3 条，说明为什么采纳/否决多空各自的观点）\n"
    "**主要风险**：（1-2 条，以及触发什么信号要改变决策）\n"
    "**一句话总结**：（给小白的大白话结论）\n\n"
    "注意：这是投资学习用途、非严肃投资建议，但你仍要给出明确可执行的方案。基于给定数据，不要编造。"
)


_ANALYST_SYS = (
    "你是一名专业的【证券分析师】，在一个投资学习聊天室里。"
    "用户问的不是「要不要买卖」的决策问题，而是想了解情况——比如某只股票为什么涨跌、"
    "最近新闻怎么解读、基本面/技术面是什么状态等。"
    "请基于给定的实时行情事实和近期新闻，直接、清楚地回答用户的问题，"
    "可以结合用户的持仓背景。用中文，markdown 分点，控制在 300 字内，"
    "必须基于给定数据与新闻，不要编造价格或事实。不要强行给买卖建议——除非用户问的就是决策。"
)

_ROUTER_SYS = (
    "你是一个意图分类器，用在一个【股票投资聊天室】里。"
    "判断用户这句话属于哪一类，只输出一个大写英文词，不要任何解释或标点：\n"
    "- DECISION：在问某只股票要不要操作 / 怎么操作（买卖、建仓、加仓、减仓、清仓、止盈、止损、是否持有、什么价位等决策）\n"
    "- ANALYSIS：在问某只股票或市场的情况 / 原因 / 解读 / 基本面 / 技术面 / 新闻含义（属于了解信息，不是买卖决策）\n"
    "- CHITCHAT：与股票投资无关的闲聊、寒暄、或无意义内容\n"
    "只输出 DECISION、ANALYSIS、CHITCHAT 三者之一。"
)


def _parse_intent(raw):
    up = (raw or "").strip().upper()
    for cat in ("CHITCHAT", "ANALYSIS", "DECISION"):
        if cat in up:
            return cat
    return "DECISION"


def classify_topic(topic):
    """用 LLM 判断议题意图，返回 'DECISION' / 'ANALYSIS' / 'CHITCHAT'。出错默认 DECISION。"""
    try:
        return _parse_intent(llm.call_role("router", _ROUTER_SYS, f"用户这句话：「{topic}」\n它属于哪一类？"))
    except Exception:
        return "DECISION"


def _logged_call(session, role, system, user):
    """调用某角色并把这一轮（提示词/模型/输出/耗时）记进 session 日志。"""
    try:
        cfg = config.resolve_role(role)
        model = f"{cfg['provider']}:{cfg['model']}"
    except Exception:
        model = "?"
    t0 = time.time()
    out = _safe_call(role, system, user)
    session["turns"].append({
        "role": role,
        "name": ROLE_META.get(role, {}).get("name", role),
        "model": model,
        "system": system,
        "user": user,
        "output": out,
        "ms": int((time.time() - t0) * 1000),
    })
    return out


def run_debate(topic, ticker):
    """生成器：先由 AI 判断议题意图，再路由到对应流程，并把整场记入日志。

    - DECISION → 多空辩论 + 裁判裁决
    - ANALYSIS → 单个分析师直接回答（同样基于行情+新闻）
    - CHITCHAT → 礼貌挡回，不查数据、不走流程

    每个 yield 元素形如 {"role","name","avatar","content"} 或 {"error": "..."}。
    无论正常结束还是中途断开，finally 都会落盘日志（logs/）。
    """
    topic = (topic or "").strip()
    ticker = (ticker or "").strip().upper()
    session = {"topic": topic, "ticker": ticker, "intent": None,
               "context": None, "turns": [], "messages": []}

    def emit(ev):
        """记录可展示消息（用于历史回放）后再交给上层 yield。"""
        if "error" in ev:
            session["messages"].append({"role": "error", "name": "系统", "avatar": "⚠️",
                                        "content": ev["error"]})
        else:
            session["messages"].append(ev)
        return ev

    try:
        # 0) 先判意图（这一步也记进 turns，方便排查误判）
        raw = _logged_call(session, "router", _ROUTER_SYS,
                           f"用户这句话：「{topic}」\n它属于哪一类？")
        intent = _parse_intent(raw)
        session["intent"] = intent

        if intent == "CHITCHAT":
            yield emit(_event("host", "这看起来不是投资相关的问题哦～ 我专注于帮你分析持仓和个股。"
                                      "试试问「我的 MU 现在该怎么操作？」或「GOOGL 今天为什么跌？」"))
            return

        if not ticker:
            yield emit({"error": "请先选择或输入一个股票代码（如 MU、GOOGL）。"})
            return

        try:
            shared, _mc, pieces = _build_shared(topic, ticker)
            session["context"] = pieces
        except Exception as e:  # 行情拉取失败
            yield emit({"error": f"获取 {ticker} 行情失败：{e}"})
            return

        # ANALYSIS：分析师直接回答
        if intent == "ANALYSIS":
            ans = _logged_call(session, "analyst", _ANALYST_SYS,
                               shared + "\n请作为分析师直接回答上面的议题。")
            yield emit(_event("analyst", ans))
            return

        # DECISION：多空辩论 + 裁判
        transcript = shared
        bull = _logged_call(session, "bull", _BULL_SYS, transcript + "\n请作为多头发言。")
        yield emit(_event("bull", bull))
        transcript += f"\n\n【多头研究员的发言】\n{bull}\n"

        bear = _logged_call(session, "bear", _BEAR_SYS, transcript + "\n请作为空头发言，并可反驳多头。")
        yield emit(_event("bear", bear))
        transcript += f"\n\n【空头研究员的发言】\n{bear}\n"

        # 只给组合经理注入该标的过往结论，防止长期持有者被短期噪音带着天天翻烧饼
        history = logbook.recent_decisions(ticker, limit=3)
        hist_block = ""
        if history:
            lines = "\n".join(f"- {h['time']}：{h['summary']}" for h in history)
            hist_block = (
                "\n\n【该标的过往结论摘要（最新在前）】\n" + lines +
                "\n（提醒：除非长期逻辑/基本面出现实质变化，否则应与过往结论保持连贯。）"
            )
        judge = _logged_call(session, "judge", _JUDGE_SYS,
                             transcript + hist_block + "\n请作为组合经理给出最终裁决。")
        yield emit(_event("judge", judge))
    finally:
        try:
            logbook.save_session(session)
        except Exception:
            pass


def _safe_call(role, system, user):
    try:
        return llm.call_role(role, system, user)
    except Exception as e:
        return f"⚠️ {ROLE_META[role]['name']} 调用失败：{e}"


def _event(role, content):
    meta = ROLE_META[role]
    return {"role": role, "name": meta["name"], "avatar": meta["avatar"], "content": content}
