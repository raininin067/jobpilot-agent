# -*- coding: utf-8 -*-
"""SQLite 持久化层测试：去重 / 升级 / 历史。"""
from jobpilot.storage import Storage, make_job_key


def test_make_job_key_stable():
    assert make_job_key("字节跳动", "后端开发") == make_job_key("字节跳动", "后端开发")
    assert make_job_key("a", "b") != make_job_key("b", "a")
    assert len(make_job_key("字节跳动", "后端开发")) == 16


def test_dedup_insert_once(tmp_path):
    s = Storage(tmp_path / "t.db")
    key = make_job_key("字节跳动", "后端开发")
    assert s.is_duplicate(key) is False
    assert s.save_application(key, "后端开发", company="字节跳动", score=88, status="applied") is True
    assert s.is_duplicate(key) is True
    assert s.save_application(key, "后端开发", company="字节跳动", score=88, status="applied") is False
    assert len(s.list_applications()) == 1


def test_watchlist_upgrade(tmp_path):
    s = Storage(tmp_path / "t.db")
    key = make_job_key("腾讯", "AI Agent 研发工程师")
    s.save_application(key, "AI Agent 研发工程师", company="腾讯", score=60, status="watchlist")
    assert s.get_application(key)["status"] == "watchlist"
    assert s.update_application(key, status="applied", score=88) is True
    row = s.get_application(key)
    assert row["status"] == "applied"
    assert row["score"] == 88


def test_analysis_history_and_last_score(tmp_path):
    s = Storage(tmp_path / "t.db")
    assert s.last_score("t1") is None
    s.save_analysis("t1", "上海大模型实习", 70, "plan-a")
    s.save_analysis("t1", "上海大模型实习", 85, "plan-b")
    s.save_analysis("t2", "北京后端", 90, "plan-c")
    assert s.last_score("t1") == 85          # 只看本线程最后一轮
    assert s.last_score() == 90              # 全局最后一轮
    hist = s.list_history("t1")
    assert [h["score"] for h in hist] == [85, 70]


def test_clear(tmp_path):
    s = Storage(tmp_path / "t.db")
    key = make_job_key("阿里云", "后端实习生")
    s.save_application(key, "后端实习生", company="阿里云", score=66)
    assert s.clear_applications() == 1
    assert s.list_applications() == []