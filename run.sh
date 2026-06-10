#!/usr/bin/env bash
# 启动股票辩论室。零依赖，只需系统自带 python3。
cd "$(dirname "$0")"
exec python3 server.py
