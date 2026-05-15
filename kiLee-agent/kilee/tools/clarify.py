"""Clarify 工具 — 主动向用户提问澄清需求（借鉴 hermes-agent clarify_tool）"""
from kilee.tools import ToolCategory

TOOL_CATEGORY = ToolCategory.COMMUNICATION
TOOL_METADATA = {"interactive": True}


import json
from typing import List, Optional

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "clarify",
        "description": (
            "当任务不明确、有歧义或缺少关键信息时，向用户提问。"
            "提供选项时用户可直接选择，不提供则开放作答。"
            "不要过度使用——只在真正需要澄清时才调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题"},
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "最多4个选项（可选）",
                },
            },
            "required": ["question"],
        },
    },
}

# 由 agent 主循环注入的回调
_callback = None

def set_callback(cb):
    global _callback
    _callback = cb

def tool_run(question: str, choices: List[str] = None) -> str:
    if not question.strip():
        return "[ERROR] 问题不能为空"

    if choices:
        choices = [c.strip() for c in choices[:4] if c.strip()]

    if _callback:
        return _callback(question, choices)

    # 默认回退：直接在终端交互
    return _terminal_ask(question, choices)

run = tool_run

def _terminal_ask(question: str, choices: Optional[List[str]]) -> str:
    from rich.console import Console
    from kilee import theme
    c = Console(highlight=False)
    ac, dm = theme.C["accent"], theme.C["dim"]

    c.print(f"\n[{ac}]◈ 需要确认[/]")
    c.print(f"  [{ac}]{question}[/]")

    if choices:
        for i, choice in enumerate(choices, 1):
            c.print(f"  [{dm}]{i}.[/] {choice}")
        c.print(f"  [{dm}]{len(choices)+1}.[/] 其他（手动输入）")
        c.print()
        try:
            raw = input("  选择 > ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                pass
            return raw
        except (KeyboardInterrupt, EOFError):
            return "(用户取消)"
    else:
        c.print()
        try:
            return input("  回答 > ").strip() or "(无回答)"
        except (KeyboardInterrupt, EOFError):
            return "(用户取消)"
