"""LLM 客户端：纯标准库调用 Gemini / DeepSeek 的 REST 接口。

每次调用返回完整文本（角色级别发言）。错误以异常抛出，由上层转成可读提示。
"""

import json
import urllib.request
import urllib.error

import config


class LLMError(Exception):
    pass


def _post_json(url, payload, headers, timeout=90):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise LLMError(f"HTTP {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        raise LLMError(f"网络错误: {e.reason}")


def _call_gemini(model, system, user, temperature, key):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature},
    }
    resp = _post_json(url, payload, {"Content-Type": "application/json"})
    try:
        cands = resp.get("candidates") or []
        if not cands:
            raise LLMError(f"Gemini 无返回（可能被安全策略拦截）: {json.dumps(resp)[:400]}")
        parts = cands[0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"Gemini 响应解析失败: {json.dumps(resp)[:400]}")


def _call_deepseek(model, system, user, temperature, key):
    url = "https://api.deepseek.com/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    resp = _post_json(url, payload, headers)
    try:
        return resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"DeepSeek 响应解析失败: {json.dumps(resp)[:400]}")


def call_role(role, system, user):
    """按角色配置调用对应模型，返回文本。"""
    cfg = config.resolve_role(role)
    provider = cfg["provider"]
    model = cfg["model"]
    temperature = cfg.get("temperature", 0.7)
    key = config.get_api_key(provider)
    if not key:
        raise LLMError(
            f"缺少 {provider} 的 API key。请在 .env 里设置 "
            f"{'GEMINI_API_KEY' if provider == 'gemini' else 'DEEPSEEK_API_KEY'}"
        )
    if provider == "gemini":
        return _call_gemini(model, system, user, temperature, key)
    if provider == "deepseek":
        return _call_deepseek(model, system, user, temperature, key)
    raise LLMError(f"未知 provider: {provider}")
