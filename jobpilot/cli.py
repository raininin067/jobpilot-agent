# -*- coding: utf-8 -*-
"""
JobPilot - 命令行入口

用法示例
--------
    # 1) 环境自检：打印配置项是否就绪（不调用任何 API）
    python -m jobpilot.cli doctor

    # 2) 跑一轮完整求职分析（可配合 Windows 任务计划程序做定时扫描）
    python -m jobpilot.cli scan --query "上海 大模型实习" --resume resume.txt

    # 3) 查看投递记录看板
    python -m jobpilot.cli history

    # 4) 清理投递记录
    python -m jobpilot.cli clear
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jobpilot.config import Settings
from jobpilot.storage import Storage
from jobpilot.workflow import build_default_app, format_report, run_analysis


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jobpilot",
        description="🧭 JobPilot-Agent：基于 LangGraph 的多智能体秋招护航系统（命令行版）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="环境自检：检查 Key / 数据 / RAG 是否就绪")

    scan = sub.add_parser("scan", help="执行一轮求职分析（咨询师模式：适合定时调用）")
    scan.add_argument("--query", "-q", required=True, help="求职意向，例如：上海 大模型实习")
    scan.add_argument("--resume", "-r", default="", help="简历文件路径（.txt/.md/.pdf）或直接粘贴的文本")
    scan.add_argument("--thread-id", default="scan", help="会话 ID（默认 scan，用于记忆隔离）")
    scan.add_argument("--report", default="", help="可选：把报告写到这个 .md 文件路径")

    sub.add_parser("history", help="列出投递/收藏记录")
    sub.add_parser("clear", help="清空投递/收藏记录")

    return p


def _read_resume(path_or_text: str) -> str:
    """简历来源：文件路径（txt/md/pdf）或纯文本。"""
    if not path_or_text:
        return ""
    candidate = Path(path_or_text)
    if candidate.is_file():
        if candidate.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(candidate))
                return "".join((page.extract_text() or "") for page in reader.pages)[:6000]
            except Exception as exc:  # noqa: BLE001
                print(f"[警告] PDF 解析失败（{exc}），按空简历处理")
                return ""
        return candidate.read_text(encoding="utf-8", errors="ignore")[:6000]
    return path_or_text[:6000]


def cmd_doctor(settings: Settings) -> int:
    print("=== JobPilot 环境自检 ===\n")
    checks = [
        ("DeepSeek API Key", settings.has_llm_key()),
        ("DeepSeek 模型", settings.deepseek_model, settings.deepseek_base_url),
        ("Tavily Key（实时搜索）", bool(settings.tavily_api_key), "缺省将降级为纯 RAG"),
        ("Webhook（手机推送）", bool(settings.webhook_url), "缺省仅控制台输出"),
        ("岗位库文件", settings.jobs_data_path.is_file(), str(settings.jobs_data_path)),
        ("RAG Embedding 模型", bool(settings.embed_model), "首次运行会现场下载（默认 hf-mirror）"),
    ]
    ok = True
    for name, passed, *hint in checks:
        mark = "✅" if passed else "❌"
        print(f"  {mark} {name}" + (f"  ({hint[0]})" if hint and not passed else ""))
        ok = ok and passed
    print("\n" + ("一切就绪，可以 `python -m jobpilot.cli scan -q '…'`" if ok else "补齐 ❌ 项后即可使用"))
    return 0 if ok else 1


def cmd_scan(settings: Settings, args) -> int:
    if not settings.has_llm_key():
        print("❌ 未配置 DEEPSEEK_API_KEY（.env 或环境变量），退出。")
        return 1

    print(f"=== 开始求职分析：{args.query} ===\n")
    app, storage = build_default_app(settings, thread_id=args.thread_id)

    def on_step(node: str, update: dict) -> None:
        print(f"  [完成] {node} -> {list(update.keys())}")

    result = run_analysis(
        app,
        query=args.query,
        resume_text=_read_resume(args.resume),
        thread_id=args.thread_id,
        storage=storage,
        on_step=on_step,
    )

    if result.get("_error"):
        print(f"\n❌ 流程异常：{result['_error']}")
        return 1

    print("\n" + "=" * 46)
    print(format_report(result, args.query))
    if args.report:
        Path(args.report).write_text(format_report(result, args.query), encoding="utf-8")
        print(f"（报告已写入 {args.report}）")
    return 0


def cmd_history(settings: Settings) -> int:
    storage = Storage(settings.db_path)
    rows = storage.list_applications()
    print(f"=== 投递/收藏记录（共 {len(rows)} 条）===\n")
    if not rows:
        print("（暂无记录——跑一轮 scan 或在使用 Web 版分析后自动生成）")
        return 0
    for r in rows:
        mark = "🔥已投递" if r["status"] == "applied" else "📌收藏"
        print(f"  {mark}  {r['job_title']}  {r['company']}  匹配{r['score']}分  {r['created_at']}")
    return 0


def cmd_clear(settings: Settings) -> int:
    storage = Storage(settings.db_path)
    n = storage.clear_applications()
    print(f"已清空 {n} 条投递/收藏记录。")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，跑不了 emoji；统一切 UTF-8（失败也不崩）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 —— 非终端环境下 reconfigure 可能不可用
            pass
    args = _build_parser().parse_args(argv)
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "doctor":
        return cmd_doctor(settings)
    if args.command == "scan":
        return cmd_scan(settings, args)
    if args.command == "history":
        return cmd_history(settings)
    if args.command == "clear":
        return cmd_clear(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())