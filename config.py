"""配置加载：从 config.json 读取角色→模型映射，从环境变量 / .env 读取 API key。"""

import json
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_ROOT, "config.json")
_ENV_PATH = os.path.join(_ROOT, ".env")


def _load_dotenv():
    """极简 .env 解析：KEY=VALUE 一行一个，# 注释。不覆盖已存在的真实环境变量。"""
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


_load_dotenv()


def load_config():
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_api_key(provider):
    if provider == "gemini":
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if provider == "deepseek":
        return os.environ.get("DEEPSEEK_API_KEY")
    return None


def resolve_role(role):
    """返回某角色对应的模型配置 dict（含 provider/model/temperature）。

    若配置里没有该角色（如新增的 analyst），回退到 judge 的模型。
    """
    cfg = load_config()
    model_key = cfg["roles"].get(role) or cfg["roles"].get("judge")
    if model_key is None:
        raise ValueError(f"配置里没有角色 {role}，也没有 judge 可回退")
    model_cfg = cfg["models"].get(model_key)
    if model_cfg is None:
        raise ValueError(f"配置里没有模型 {model_key}")
    return {"_key": model_key, **model_cfg}


def save_roles(roles):
    """更新角色→模型映射并写回 config.json，保留其它字段。只接受合法的 model key。"""
    cfg = load_config()
    valid = set(cfg.get("models", {}).keys())
    new = dict(cfg.get("roles", {}))
    for r in ("bull", "bear", "judge"):
        if r in roles and roles[r] in valid:
            new[r] = roles[r]
    cfg["roles"] = new
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return new


def status():
    """返回各 provider 的 key 是否就绪，用于前端提示。"""
    return {
        "gemini": bool(get_api_key("gemini")),
        "deepseek": bool(get_api_key("deepseek")),
    }
