# -*- coding: utf-8 -*-
"""
JobPilot - 消息通知（Webhook）

支持 Server酱 / 企业微信群机器人 / 飞书机器人等任意
「POST JSON 即推送」的 Webhook 渠道；未配置时静默跳过。
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class WebhookNotifier:
    def __init__(self, url: str = ""):
        self.url = url

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def send(self, title: str, content: str, *, timeout: float = 5.0) -> bool:
        """推送一条文本通知。成功返回 True；未配置/失败返回 False（不抛异常）。"""
        if not self.url:
            logger.info("[notify] 未配置 WEBHOOK_URL，跳过推送：%s", title)
            return False
        try:
            payload = {"msgtype": "text", "text": {"content": f"🚨【JobPilot 秋招护航】\n{title}\n\n{content}"}}
            resp = requests.post(self.url, json=payload, timeout=timeout)
            resp.raise_for_status()
            logger.info("[notify] 推送成功：%s", title)
            return True
        except Exception as exc:  # noqa: BLE001 —— 通知失败绝不能拖垮主流程
            logger.warning("[notify] 推送失败：%s", exc)
            return False


class NullNotifier:
    """测试桩：记录最后一次通知内容。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    @property
    def enabled(self) -> bool:
        return True

    def send(self, title: str, content: str, *, timeout: float = 5.0) -> bool:
        self.calls.append((title, content))
        return True