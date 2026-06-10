"""辩论日志：每场存一份完整 JSON（提示词 / 注入数据 / 新闻 / 各角色输出 / 耗时），
并维护一个 index.jsonl 便于列表与回看。用于历史回放和后续调优。
"""

import json
import os
import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_ROOT, "logs")
_INDEX = os.path.join(LOGS_DIR, "index.jsonl")


def save_session(session):
    os.makedirs(LOGS_DIR, exist_ok=True)
    now = datetime.datetime.now()
    session.setdefault("time", now.strftime("%Y-%m-%d %H:%M:%S"))
    stamp = now.strftime("%Y%m%d_%H%M%S")
    tk = (session.get("ticker") or "NA").upper()
    fname = f"{stamp}_{tk}_{session.get('intent') or 'NA'}.json"
    with open(os.path.join(LOGS_DIR, fname), "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    entry = {
        "file": fname,
        "time": session["time"],
        "ticker": tk,
        "intent": session.get("intent"),
        "topic": session.get("topic"),
    }
    with open(_INDEX, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return fname


def list_sessions(limit=100):
    """返回最近的会话索引（倒序，最新在前）。"""
    if not os.path.exists(_INDEX):
        return []
    out = []
    with open(_INDEX, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    out.reverse()
    return out[:limit]


def read_session(fname):
    """安全读取单场日志（限制在 logs 目录内）。"""
    path = os.path.normpath(os.path.join(LOGS_DIR, os.path.basename(fname)))
    if not path.startswith(LOGS_DIR) or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _condense(text, maxlen=220):
    """从裁判输出里抽取「操作建议 / 一句话总结」，内容若在下一行也能补抓；没有就截断。"""
    lines = [ln.strip().lstrip("*# ").strip().replace("**", "") for ln in (text or "").splitlines()]
    picked = []
    for idx, l in enumerate(lines):
        for k in ("操作建议", "一句话总结"):
            if l.startswith(k):
                val = l.split("：", 1)[-1].split(":", 1)[-1].strip() if ("：" in l or ":" in l) else ""
                if not val:  # 内容写在下一行
                    for nxt in lines[idx + 1:]:
                        if nxt:
                            val = nxt
                            break
                if val:
                    picked.append(f"{k}：{val}")
    s = " / ".join(picked) if picked else (text or "").strip().replace("\n", " ")
    return s[:maxlen]


def recent_decisions(ticker, limit=3):
    """返回某标的最近的几次【决策类】裁决摘要（最新在前），用于喂给组合经理防反复。"""
    ticker = (ticker or "").upper()
    out = []
    for e in list_sessions(500):
        if (e.get("ticker") or "").upper() != ticker or e.get("intent") != "DECISION":
            continue
        s = read_session(e["file"])
        if not s:
            continue
        concl = None
        for t in s.get("turns", []):
            if t.get("role") == "judge":
                concl = t.get("output")
        if concl:
            out.append({"time": e.get("time"), "summary": _condense(concl)})
        if len(out) >= limit:
            break
    return out
