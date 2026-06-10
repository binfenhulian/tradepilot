"""新闻模块：从 Yahoo Finance search 接口拉个股/宏观新闻（纯标准库 urllib）。

设计照搬 TradingAgents 的思路：新闻当成「结构化数据源」由后端统一拉取，
作为同一份事实注入所有 AI 角色，而不是让模型各自联网搜。
（解析逻辑改编自 TradingAgents 的 _extract_article_data；取数用 urllib 替掉 yfinance 包以保持零依赖。）
"""

import json
import time
import datetime
import urllib.request
import urllib.parse

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"

_cache = {}
_CACHE_TTL = 120  # 新闻缓存久一点


def _search(query, count):
    key = f"{query}:{count}"
    now = time.time()
    if key in _cache and now - _cache[key][0] < _CACHE_TTL:
        return _cache[key][1]
    params = urllib.parse.urlencode({
        "q": query, "newsCount": count, "quotesCount": 0, "enableFuzzyQuery": "false",
    })
    req = urllib.request.Request(f"{_SEARCH}?{params}", headers=_UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.load(r)
    news = data.get("news", []) or []
    _cache[key] = (now, news)
    return news


def _extract(article):
    """解析单条新闻，兼容 Yahoo 的扁平结构与嵌套 content 结构（改编自 TradingAgents）。"""
    if "content" in article:  # 嵌套结构
        c = article["content"]
        url_obj = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
        ts = None
        pub = c.get("pubDate", "")
        if pub:
            try:
                ts = datetime.datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                ts = None
        return {
            "title": c.get("title", "无标题"),
            "summary": c.get("summary", ""),
            "publisher": (c.get("provider") or {}).get("displayName", "未知来源"),
            "link": url_obj.get("url", ""),
            "ts": ts,
        }
    # 扁平结构
    return {
        "title": article.get("title", "无标题"),
        "summary": article.get("summary", ""),
        "publisher": article.get("publisher", "未知来源"),
        "link": article.get("link", ""),
        "ts": article.get("providerPublishTime"),
    }


def _fmt_date(ts):
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return ""


def get_news(ticker, limit=6):
    """个股近期新闻，返回 [{title, publisher, date, summary, link}]。"""
    try:
        raw = _search(ticker, limit)
    except Exception as e:
        return {"error": str(e), "items": []}
    items = []
    for a in raw[:limit]:
        d = _extract(a)
        items.append({
            "title": d["title"], "publisher": d["publisher"],
            "date": _fmt_date(d["ts"]), "summary": d["summary"], "link": d["link"],
        })
    return {"items": items}


# 宏观新闻用几个固定查询（照搬 TradingAgents 的 macro queries）
_MACRO_QUERIES = ["stock market economy", "Federal Reserve interest rates", "inflation outlook"]


def get_global_news(limit=4):
    items, seen = [], set()
    for q in _MACRO_QUERIES:
        try:
            raw = _search(q, limit)
        except Exception:
            continue
        for a in raw:
            d = _extract(a)
            if d["title"] and d["title"] not in seen:
                seen.add(d["title"])
                items.append({
                    "title": d["title"], "publisher": d["publisher"], "date": _fmt_date(d["ts"]),
                })
        if len(items) >= limit:
            break
    return {"items": items[:limit]}


def build_news_context(ticker, include_global=False):
    """组装喂给 LLM 的新闻文本块。"""
    lines = []
    n = get_news(ticker, limit=6)
    if n.get("items"):
        lines.append(f"【{ticker.upper()} 近期新闻】")
        for it in n["items"]:
            head = f"- ({it['date']}) {it['title']} —— {it['publisher']}" if it["date"] else f"- {it['title']} —— {it['publisher']}"
            lines.append(head)
            if it["summary"]:
                lines.append(f"  摘要：{it['summary'][:160]}")
    if include_global:
        g = get_global_news(limit=4)
        if g.get("items"):
            lines.append("\n【宏观/市场新闻】")
            for it in g["items"]:
                lines.append(f"- {it['title']} —— {it['publisher']}")
    if not lines:
        return ""
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(build_news_context(sys.argv[1] if len(sys.argv) > 1 else "MU"))
