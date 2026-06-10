"""持仓存储：读写 data/holdings.json，支持增删改。前端可自行管理。"""

import json
import os
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_ROOT, "data", "holdings.json")
_PROFILE_PATH = os.path.join(_ROOT, "data", "profile.json")
_lock = threading.Lock()

_DEFAULT_PROFILE = {
    "preferences": "中长线为主，能接受中等波动；偏好科技/半导体成长股；"
    "单只仓位不超过总仓位 30%；不做杠杆，不追高，回调分批建仓。"
}


def _read():
    if not os.path.exists(_PATH):
        return []
    with open(_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write(items):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def list_holdings():
    return _read()


def upsert_holding(ticker, shares, cost):
    """新增或更新一只持仓（按 ticker 去重，大写）。"""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker 不能为空")
    shares = float(shares)
    cost = float(cost)
    with _lock:
        items = _read()
        for it in items:
            if it["ticker"] == ticker:
                it["shares"] = shares
                it["cost"] = cost
                _write(items)
                return it
        new = {"ticker": ticker, "shares": shares, "cost": cost}
        items.append(new)
        _write(items)
        return new


def delete_holding(ticker):
    ticker = (ticker or "").strip().upper()
    with _lock:
        items = _read()
        items2 = [it for it in items if it["ticker"] != ticker]
        _write(items2)
        return len(items2) != len(items)


# ---------- 投资偏好 ----------

def get_profile():
    if not os.path.exists(_PROFILE_PATH):
        return dict(_DEFAULT_PROFILE)
    with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return dict(_DEFAULT_PROFILE)


def set_profile(preferences):
    with _lock:
        os.makedirs(os.path.dirname(_PROFILE_PATH), exist_ok=True)
        data = {"preferences": (preferences or "").strip()}
        with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
