# -*- coding: utf-8 -*-
"""通知模块测试。"""
from jobpilot.notify import NullNotifier, WebhookNotifier


def test_notifier_skips_without_url(monkeypatch):
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    n = WebhookNotifier("")
    assert n.enabled is False
    assert n.send("title", "content") is False


def test_notifier_posts_json(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)
    n = WebhookNotifier("https://example.com/hook")
    assert n.send("岗位", "内容", timeout=3.0) is True
    assert captured["url"] == "https://example.com/hook"
    assert captured["timeout"] == 3.0
    assert captured["json"]["msgtype"] == "text"
    assert "岗位" in captured["json"]["text"]["content"]


def test_notifier_never_raises(monkeypatch):
    def boom(url, json, timeout):
        raise ConnectionError("network down")

    monkeypatch.setattr("requests.post", boom)
    n = WebhookNotifier("https://example.com/hook")
    assert n.send("t", "c") is False  # 失败静默返回 False


def test_null_notifier_records_calls():
    n = NullNotifier()
    assert n.send("标题A", "内容A") is True
    assert n.send("标题B", "内容B") is True
    assert n.calls == [("标题A", "内容A"), ("标题B", "内容B")]