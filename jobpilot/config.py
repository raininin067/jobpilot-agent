# -*- coding: utf-8 -*-
"""
JobPilot - 配置模块
零第三方依赖的环境变量加载（兼容 .env 文件），所有可调参数集中在这里。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """读取 .env 文件补充环境变量（不覆盖已存在的变量，兼容 utf-8-sig 带 BOM）。"""
    candidates = [path] if path else [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    for p in candidates:
        if p and p.is_file():
            for raw in p.read_text(encoding="utf-8-sig").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
            return


@dataclass(frozen=True)
class Settings:
    """集中管理全部可调参数；从环境变量构造，默认值即开箱即用的配置。"""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    deepseek_temperature: float = 0.0

    tavily_api_key: str = ""
    webhook_url: str = ""

    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    rag_top_k: int = 3
    match_threshold: int = 80
    embed_model: str = "BAAI/bge-small-zh-v1.5"

    @classmethod
    def from_env(cls, env: dict | None = None, *, load_env_file: bool = True) -> "Settings":
        if load_env_file:
            load_dotenv()
        e = dict(env) if env is not None else os.environ

        def _int(name: str, default: int) -> int:
            try:
                return int(e.get(name, default))
            except (TypeError, ValueError):
                return default

        def _float(name: str, default: float) -> float:
            try:
                return float(e.get(name, default))
            except (TypeError, ValueError):
                return default

        data_dir = Path(e.get("JOBPILOT_DATA_DIR", PROJECT_ROOT / "data"))
        if not data_dir.is_absolute():
            data_dir = (PROJECT_ROOT / data_dir).resolve()

        return cls(
            deepseek_api_key=e.get("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=e.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            deepseek_model=e.get("DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_temperature=_float("DEEPSEEK_TEMPERATURE", 0.0),
            tavily_api_key=e.get("TAVILY_API_KEY", ""),
            webhook_url=e.get("WEBHOOK_URL", ""),
            data_dir=data_dir,
            rag_top_k=_int("JOBPILOT_RAG_TOP_K", 3),
            match_threshold=_int("JOBPILOT_MATCH_THRESHOLD", 80),
            embed_model=e.get("JOBPILOT_EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
        )

    # ---------------------------------------------------------------
    # 派生路径
    # ---------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobpilot.db"

    @property
    def jobs_data_path(self) -> Path:
        return self.data_dir / "jobs_data.json"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "rag_chroma"

    def has_llm_key(self) -> bool:
        return bool(self.deepseek_api_key)

    def validate(self) -> None:
        """启动前校验：缺少 LLM Key 时给出可操作的提示。"""
        if not self.has_llm_key():
            raise RuntimeError(
                "未配置 LLM 的 API Key ！三种方式任选其一：\n"
                "  1) 在本项目根目录创建 .env，写入 DEEPSEEK_API_KEY=sk-xxxx\n"
                "  2) 设置环境变量 DEEPSEEK_API_KEY\n"
                "  3) Streamlit 界面侧边栏里临时输入 Key（仅本次会话内存，不落盘）"
            )