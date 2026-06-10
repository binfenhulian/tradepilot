"""行情模块：纯标准库从 Yahoo Finance 拉实时价 / 历史收盘，并计算技术指标。

设计理念（参考 TradingAgents）：定量数据由后端统一拉取并算好，
作为「同一份事实」喂给所有 AI 角色，而不是让模型各自联网瞎猜。
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import datetime

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

# 简单内存缓存，避免短时间内重复打 Yahoo（key -> (ts, data)）
_cache = {}
_CACHE_TTL = 20  # 秒


def _fetch_chart(symbol, rng="1y", interval="1d", prepost=False, ttl=_CACHE_TTL):
    key = f"{symbol}:{rng}:{interval}:{prepost}"
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    url = f"{_BASE}{urllib.parse.quote(symbol)}?range={rng}&interval={interval}"
    if prepost:
        url += "&includePrePost=true"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.load(r)
    result = data["chart"]["result"]
    if not result:
        raise ValueError(f"未找到标的 {symbol}")
    res = result[0]
    _cache[key] = (now, res)
    return res


def _clean_closes(res):
    """返回 [(timestamp, close), ...]，过滤掉 None。"""
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    return [(t, c) for t, c in zip(ts, closes) if c is not None]


# ---------- 技术指标（纯 Python，无 numpy） ----------

def _sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _ema_series(values, n):
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    ema = sum(values[:n]) / n
    out = [ema]
    for v in values[n:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _ema(values, n):
    s = _ema_series(values, n)
    return s[-1] if s else None


def _rsi(values, n=14):
    if len(values) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(values):
    if len(values) < 35:
        return None, None, None
    ema12 = _ema_series(values, 12)
    ema26 = _ema_series(values, 26)
    # 对齐到相同长度（取尾部）
    m = min(len(ema12), len(ema26))
    macd_line = [ema12[-m + i] - ema26[-m + i] for i in range(m)]
    signal = _ema_series(macd_line, 9)
    if not signal:
        return macd_line[-1], None, None
    macd_v = macd_line[-1]
    sig_v = signal[-1]
    return macd_v, sig_v, macd_v - sig_v


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a - b) / b * 100


def _round(x, d=2):
    return None if x is None else round(x, d)


# ---------- 对外接口 ----------

_STATE_LABEL = {"PRE": "盘前", "PREPRE": "盘前", "POST": "盘后", "POSTPOST": "盘后",
                "REGULAR": "盘中", "CLOSED": "休市"}


def _et_offset(dt_utc):
    """美东相对 UTC 的小时偏移：夏令时 -4(EDT)，冬令时 -5(EST)。"""
    y = dt_utc.year
    mar = datetime.date(y, 3, 1)
    second_sun_mar = mar + datetime.timedelta(days=(6 - mar.weekday()) % 7 + 7)
    nov = datetime.date(y, 11, 1)
    first_sun_nov = nov + datetime.timedelta(days=(6 - nov.weekday()) % 7)
    return -4 if (second_sun_mar <= dt_utc.date() < first_sun_nov) else -5


def _to_et(dt_utc):
    return dt_utc + datetime.timedelta(hours=_et_offset(dt_utc))


def us_market_session():
    """根据当前美东时间推算时段，返回 (label, code)。不依赖 Yahoo 的 marketState。"""
    et = _to_et(datetime.datetime.utcnow())
    if et.weekday() >= 5:  # 周末
        return "休市", "CLOSED"
    mins = et.hour * 60 + et.minute
    if 4 * 60 <= mins < 9 * 60 + 30:
        return "盘前", "PRE"
    if 9 * 60 + 30 <= mins < 16 * 60:
        return "盘中", "REGULAR"
    if 16 * 60 <= mins < 20 * 60:
        return "盘后", "POST"
    return "休市", "CLOSED"


def _fmt_quote_time(ts):
    """把行情时间戳格式化成美东时间字符串，标明是否收盘价。"""
    if not ts:
        return None
    et = _to_et(datetime.datetime.utcfromtimestamp(ts))
    return et.strftime("%m-%d %H:%M ET")


def _extended(meta, ref):
    """提取盘前/盘后报价（相对常规盘价 ref 计算涨跌）。无则返回 None。"""
    state = meta.get("marketState")
    pre = meta.get("preMarketPrice")
    post = meta.get("postMarketPrice")
    px = None
    label = None
    if state in ("PRE", "PREPRE") and pre:
        px, label = pre, "盘前"
    elif state in ("POST", "POSTPOST", "CLOSED") and post:
        px, label = post, "盘后"
    elif post:            # marketState 缺失时的兜底
        px, label = post, "盘后"
    elif pre:
        px, label = pre, "盘前"
    if not px or not ref:
        return None
    return {"label": label, "price": _round(px), "changePct": _round(_pct(px, ref))}


def get_quote(symbol):
    """返回最新价（含盘前/盘后）、上一交易日收盘、涨跌幅、52周区间、市场时段。

    现价取自【分钟级 K 线的最后一根】——盘前/盘后也能拿到（缓存 8 秒，保证轮询拉到最新）。
    上一收盘 / 52周 / 名称取自日线（缓存 10 分钟，盘中基本不变，省请求）。
    （Yahoo 免费接口的 meta.preMarketPrice/regularMarketPrice 常滞后或为空，不可靠，故改用分钟线。）"""
    daily = _fetch_chart(symbol, rng="1mo", interval="1d", prepost=False, ttl=600)
    dmeta = daily.get("meta", {})
    dpairs = _clean_closes(daily)
    if not dpairs:
        raise ValueError(f"{symbol} 无收盘数据")

    # 现价：分钟级最后一根（含盘前盘后）；失败则回退到 meta / 日线
    live_t = dmeta.get("regularMarketTime")
    current = dmeta.get("regularMarketPrice")
    try:
        mins = _fetch_chart(symbol, rng="1d", interval="1m", prepost=True, ttl=8)
        mpairs = _clean_closes(mins)
        if mpairs:
            live_t, current = mpairs[-1][0], mpairs[-1][1]
    except Exception:
        pass
    if current is None:
        current = dpairs[-1][1]

    # 上一交易日收盘：用日线序列推算（若最后一根是今天则取前一根）
    today = datetime.date.today()
    last_t, last_c = dpairs[-1]
    last_date = datetime.datetime.fromtimestamp(last_t).date()
    prev_close = dpairs[-2][1] if (last_date == today and len(dpairs) >= 2) else last_c

    state = _STATE_LABEL.get(dmeta.get("marketState")) or us_market_session()[0]
    return {
        "symbol": symbol.upper(),
        "name": dmeta.get("longName") or dmeta.get("shortName") or symbol.upper(),
        "currency": dmeta.get("currency", "USD"),
        "price": _round(current),
        "prevClose": _round(prev_close),
        "change": _round((current or 0) - (prev_close or 0)),
        "changePct": _round(_pct(current, prev_close)),
        "dayHigh": _round(dmeta.get("regularMarketDayHigh")),
        "dayLow": _round(dmeta.get("regularMarketDayLow")),
        "week52High": _round(dmeta.get("fiftyTwoWeekHigh")),
        "week52Low": _round(dmeta.get("fiftyTwoWeekLow")),
        "marketState": dmeta.get("marketState"),
        "marketStateLabel": state,
        "quoteTime": _fmt_quote_time(live_t),
        "extended": None,
    }


def get_sparkline(symbol, rng="3mo"):
    """返回迷你走势图用的收盘价序列。日线数据盘中几乎不变，缓存 10 分钟。"""
    res = _fetch_chart(symbol, rng=rng, interval="1d", ttl=600)
    pairs = _clean_closes(res)
    return {
        "symbol": symbol.upper(),
        "points": [_round(c) for _, c in pairs],
        "timestamps": [t for t, _ in pairs],
    }


def get_indicators(symbol):
    """计算并返回常用技术指标。基于一年日线，缓存 10 分钟。"""
    res = _fetch_chart(symbol, rng="1y", interval="1d", ttl=600)
    closes = [c for _, c in _clean_closes(res)]
    if len(closes) < 20:
        return {"note": "历史数据不足，指标不可用"}
    macd_v, sig_v, hist_v = _macd(closes)
    return {
        "sma20": _round(_sma(closes, 20)),
        "sma50": _round(_sma(closes, 50)),
        "sma200": _round(_sma(closes, 200)),
        "ema10": _round(_ema(closes, 10)),
        "rsi14": _round(_rsi(closes, 14)),
        "macd": _round(macd_v, 3),
        "macdSignal": _round(sig_v, 3),
        "macdHist": _round(hist_v, 3),
        "recentCloses": [_round(c) for c in closes[-10:]],
    }


def build_market_context(symbol):
    """组装喂给 LLM 的「行情事实卡片」（文本 + 结构化）。"""
    q = get_quote(symbol)
    ind = get_indicators(symbol)

    def fmt(x, suffix=""):
        return "N/A" if x is None else f"{x}{suffix}"

    state = q.get("marketStateLabel") or "未知"
    qt = f"（行情时间 {q['quoteTime']}）" if q.get("quoteTime") else ""
    lines = [
        f"标的：{q['symbol']}（{q['name']}） 货币：{q['currency']} 市场状态：{state}{qt}",
        f"现价（{state}）：{fmt(q['price'])}  上一交易日收盘：{fmt(q['prevClose'])}  涨跌：{fmt(q['change'])}（{fmt(q['changePct'],'%')}）",
        f"今日区间：{fmt(q['dayLow'])} ~ {fmt(q['dayHigh'])}   52周区间：{fmt(q['week52Low'])} ~ {fmt(q['week52High'])}",
    ]
    if q.get("extended"):
        e = q["extended"]
        lines.append(f"{e['label']}报价：{fmt(e['price'])}（较常规盘 {fmt(e['changePct'],'%')}）")
    if "note" not in ind:
        lines += [
            f"均线：SMA20={fmt(ind['sma20'])}  SMA50={fmt(ind['sma50'])}  SMA200={fmt(ind['sma200'])}  EMA10={fmt(ind['ema10'])}",
            f"动量：RSI14={fmt(ind['rsi14'])}（>70超买 <30超卖）",
            f"MACD：{fmt(ind['macd'])}  Signal={fmt(ind['macdSignal'])}  柱={fmt(ind['macdHist'])}",
            f"近10日收盘：{ind['recentCloses']}",
        ]
    return {"text": "\n".join(lines), "quote": q, "indicators": ind}


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "MU"
    print(build_market_context(sym)["text"])
