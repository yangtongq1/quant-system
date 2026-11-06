"""
LLM 翻译/摘要（知识板块）

职责：英文标题/摘要 → 中文。默认接智谱 GLM API（用户开发栈），key 从环境变量读取；
未配置 key 时降级返回原文，不影响采集主流程。
"""

from __future__ import annotations

import os

import requests

# 智谱 GLM API
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
API_KEY_ENV = "ZHIPU_API_KEY"


def _call_glm(prompt: str, api_key: str | None = None, model: str = "glm-4-flash") -> str:
    """调用智谱 GLM，失败返回空串。"""
    api_key = api_key or os.environ.get(API_KEY_ENV, "")
    if not api_key:
        return ""
    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=30,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001
        print(f"[translator] LLM 调用失败: {e}")
        return ""


def translate(text: str, api_key: str | None = None) -> str:
    """英文 → 中文。无 key 或失败时返回原文（降级）。"""
    if not text:
        return ""
    if not api_key and not os.environ.get(API_KEY_ENV):
        return text  # 未配置 key，降级返回原文
    prompt = f"请把下面这段英文翻译成简洁的中文（如果是标题就只翻译标题，不要额外解释）：\n\n{text}"
    out = _call_glm(prompt, api_key)
    return out or text


def summarize_zh(text: str, api_key: str | None = None) -> str:
    """英文摘要 → 中文一句话摘要。无 key 时返回空串。"""
    if not text or not os.environ.get(API_KEY_ENV):
        return ""
    prompt = f"请用一句中文概括下面这段英文的核心内容（30 字以内）：\n\n{text}"
    return _call_glm(prompt, api_key)
