"""日志（core/logger.py）：分级 + 按日滚动。"""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def get_logger(name: str = "quant", log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    """获取日志器（单例配置，按日滚动，保留 14 天）。

    防重复：同进程内多次调用（如调度器先起 paper 再起 scheduler logger）
    只配置一次 handler；不同 name 独立文件。
    """
    logger = logging.getLogger(name)

    if not logger.handlers:  # 已有 handler 则跳过（防重复输出）
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        # 文件：按日滚动
        fh = TimedRotatingFileHandler(
            Path(log_dir) / f"{name}.log", when="midnight", backupCount=14, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # 控制台
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

        logger.setLevel(level)
        logger.propagate = False

    return logger
