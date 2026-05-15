"""
KiLee Agent 核心 — 基于 Pipeline 的 v0.2 架构

┌──────────────────────────────────────────────────────────────────────┐
│                     CLI 层 (main.py → click CLI)                     │
├──────────────────────────────────────────────────────────────────────┤
│                     Pipeline 层 (pipeline/)                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  InputStage → LLMStage(含Reflection+压缩) → OutputStage     │    │
│  └─────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────┤
│                     Tool 层 (tools/ — 自注册插件 + 分类)              │
│  execute_bash  fs_read  fs_write  memory  todo  web_search  clarify │
├──────────────────────────────────────────────────────────────────────┤
│                     Core 层 (config / compressor / hooks / theme)    │
└──────────────────────────────────────────────────────────────────────┘

借鉴: Hermes (自注册工具) + OpenClaw (四层架构) + AstrBot (Pipeline+Stage)
"""

from pathlib import Path
from rich.console import Console
from kilee import config, theme
from kilee.pipeline import PipelineScheduler, PipelineContext
from kilee.pipeline.stages.llm_stage import LLMStage
from kilee.tools import memory as mem_tool
from kilee.hooks import get_hooks

console = Console(highlight=False)

# ── 系统提示模板 ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 KiLee，一个运行在终端里的 AI Agent。
你可以使用工具来帮助用户：读写文件、执行命令、编写和调试代码。

规则：
- 需要操作文件或执行命令时，直接使用工具，不要只是描述
- 执行危险操作前先说明你要做什么
- 用中文回复，代码块用markdown格式
- 当用户提到重要偏好、项目信息或需要跨会话记住的事情时，主动调用 save_memory
{project_context}{memory_context}
"""


def _load_project_context() -> str:
    """读取当前目录下的项目上下文文件（KILEE.md / CLAUDE.md / AGENTS.md）"""
    candidates = ["KILEE.md", "CLAUDE.md", "AGENTS.md", ".kilee.md"]
    cwd = Path.cwd()
    for name in candidates:
        p = cwd / name
        if p.exists():
            try:
                content = p.read_text(errors="replace").strip()
                if content:
                    return f"\n<project-context source=\"{name}\">\n{content}\n</project-context>\n"
            except Exception:
                pass
    return ""


def build_system_prompt() -> str:
    project_ctx = _load_project_context()
    memory_ctx = mem_tool.get_context()
    return SYSTEM_PROMPT.format(
        project_context=project_ctx,
        memory_context=("\n" + memory_ctx) if memory_ctx else "",
    )


def get_client():
    cfg = config.load()
    from openai import OpenAI
    return OpenAI(api_key=cfg.get("api_key", ""), base_url=cfg["base_url"]), cfg


# ── 欢迎界面 ─────────────────────────────────────────────────────────────────

def print_welcome():
    from kilee.tools import memory as mem_tool, get_tool_names
    from kilee.tips import get_random_tip
    from pathlib import Path as _Path
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    import os as _os

    cfg = config.load()
    model = cfg.get("model", "deepseek-chat")
    facts_count = len(mem_tool.list_facts())
    cwd = _os.getcwd()
    if len(cwd) > 40:
        cwd = "…" + cwd[-39:]

    ac, ac2, dm, bdr, ok, h1, h2 = (
        theme.C["accent"], theme.C["accent2"],
        theme.C["dim"], theme.C["border"],
        theme.C["ok"], theme.C["h1"], theme.C["h2"],
    )

    tool_names = get_tool_names()
    tool_tags = "  ".join(
        f"[{h2}]{theme.TOOL_ICONS.get(n, '◌')} {n}[/]"
        for n in tool_names[:6]
    )
    if len(tool_names) > 6:
        tool_tags += f"  [{dm}]+{len(tool_names)-6} more[/]"

    # ── 左侧 Logo ─────────────────────────────────────────────────────
    # 尝试加载自定义 ASCII 头像，否则使用内置渐变色 ki Logo
    _ascii_path = "/tmp/avatar_ascii.txt"
    if _os.path.exists(_ascii_path):
        with open(_ascii_path, "r") as _f:
            raw = _f.read()
        logo_widget = Text.from_ansi(raw)
    else:
        # 使用 theme 中定义的 BANNER_LOGO（已含 Rich 标记）
        logo_widget = theme.BANNER_LOGO

    # ── 右侧信息面板 ──────────────────────────────────────────────────
    info_lines = []

    # Section: Status
    info_lines.append(f"  [{ac}]◆[/] [{h1}]status[/]")
    info_lines.append(f"    [{h2}]●[/] [{dm}]model [/]{model}")
    info_lines.append(f"    [{h2}]●[/] [{dm}]cwd   [/][{dm}]{cwd}[/]")
    if facts_count:
        info_lines.append(f"    [{h2}]●[/] [{dm}]memory[/]  [{ok}]{facts_count} facts[/]")
    ctx_file = next((f for f in ["KILEE.md","CLAUDE.md","AGENTS.md",".kilee.md"] if (_Path.cwd()/f).exists()), None)
    if ctx_file:
        info_lines.append(f"    [{h2}]●[/] [{dm}]ctx   [/][{ok}]✓ {ctx_file}[/]")
    info_lines.append("")

    # Section: Tools
    info_lines.append(f"  [{ac}]◆[/] [{h1}]tools[/]")
    info_lines.append(f"    [{dm}]{tool_tags}[/]")
    info_lines.append("")

    # Section: Commands
    info_lines.append(f"  [{ac}]◆[/] [{h1}]commands[/]")
    info_lines.append(f"    [{dm}]/clear  /compact  /memory  /model  /help[/]")
    info_lines.append("")

    # Section: Tip
    tip = get_random_tip()
    info_lines.append(f"  [{ac}]◈[/] [{h1}]tip[/]")
    info_lines.append(f"    [{dm}]{tip}[/]")

    right_panel = Panel(
        "\n".join(info_lines),
        border_style=bdr,
        padding=(1, 2),
        width=64,
    )

    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True, vertical="top")
    table.add_column(no_wrap=True, vertical="top")

    table.add_row(logo_widget, right_panel)

    console.print()
    console.print(table)
    console.print()


# ── Agent 主入口（基于 Pipeline） ────────────────────────────────────────────

def run_agent(messages: list) -> str:
    """
    使用 Pipeline 系统运行 Agent（基于 Think→Act 循环）
    
    1. 创建 PipelineContext 上下文
    2. 注册 LLMStage（内含 Think→Act 循环 + Reflection + Stuck 检测）
    3. 初始化并执行 Pipeline
    
    Args:
        messages: 当前对话消息列表
    
    Returns:
        LLM 的最终文本回复
    """
    # 创建上下文
    ctx = PipelineContext()
    ctx.messages = messages

    # 创建调度器并注册 Stage
    scheduler = PipelineScheduler()
    scheduler.register(LLMStage)

    # 初始化
    scheduler.initialize(ctx)

    # 执行 Pipeline
    scheduler.run(ctx)

    return ctx.llm_response


def run_agent_with_state(messages: list) -> dict:
    """
    运行 Agent 并返回完整状态（供外部检查）
    
    Returns:
        {"response": str, "state": AgentState, "steps": int}
    """
    from kilee.schema import AgentState
    
    ctx = PipelineContext()
    ctx.messages = messages

    scheduler = PipelineScheduler()
    scheduler.register(LLMStage)
    scheduler.initialize(ctx)
    scheduler.run(ctx)

    # 从 LLMStage 获取状态
    stage = scheduler.stages[0] if scheduler.stages else None
    return {
        "response": ctx.llm_response,
        "state": getattr(stage, "state", AgentState.FINISHED),
        "steps": getattr(stage, "current_step", 0),
        "tool_results": ctx.tool_results,
    }
