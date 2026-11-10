"""配置加载（core/config.py）"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_env(path: str | Path = ".env") -> dict[str, str]:
    """加载 .env 到 os.environ（不覆盖已有值）。

    格式：KEY=VALUE 每行一条；# 开头为注释；值不加引号解析。
    敏感信息（SuperMind 账号 / API key）统一放 .env（已 gitignore），不进代码与 config.yaml。
    """
    p = Path(path)
    if not p.exists():
        return {}
    loaded: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            loaded[key] = val
    return loaded


def load_config(path: str | Path = "config/config.yaml") -> dict:
    """加载 YAML 配置，返回 dict。"""
    with open(Path(path), encoding="utf-8") as f:
        return yaml.safe_load(f)
