"""配置加载（core/config.py）"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_config(path: str | Path = "config/config.yaml") -> dict:
    """加载 YAML 配置，返回 dict。"""
    with open(Path(path), encoding="utf-8") as f:
        return yaml.safe_load(f)
