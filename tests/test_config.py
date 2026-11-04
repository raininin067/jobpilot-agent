# -*- coding: utf-8 -*-
"""配置模块测试。"""
import os

import pytest

from jobpilot.config import Settings, load_dotenv


def test_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings.from_env(None, load_env_file=False)
    assert s.deepseek_model == "deepseek-chat"
    assert s.match_threshold == 80
    assert s.rag_top_k == 3
    assert not s.has_llm_key()


def test_env_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("JOBPILOT_MATCH_THRESHOLD", "90")
    s = Settings.from_env(None, load_env_file=False)
    assert s.deepseek_api_key == "sk-test"
    assert s.match_threshold == 90


def test_invalid_int_falls_back(monkeypatch):
    monkeypatch.setenv("JOBPILOT_MATCH_THRESHOLD", "abc")
    s = Settings.from_env(None, load_env_file=False)
    assert s.match_threshold == 80


def test_data_dir_is_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DATA_DIR", str(tmp_path))
    s = Settings.from_env(None, load_env_file=False)
    assert s.db_path.parent == tmp_path


def test_dotenv_loader(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 注释\nDEEPSEEK_API_KEY=sk-from-file\nDEEPSEEK_MODEL='deepseek-reasoner'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    load_dotenv(env_file)
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-from-file"
    assert os.environ["DEEPSEEK_MODEL"] == "deepseek-reasoner"


def test_validate_raises_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings.from_env(None, load_env_file=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        s.validate()