"""
LLM Stage — Think→Act 循环（借鉴 OpenManus ToolCallAgent）

拆分为清晰的两步:
  1. think(): 调用 LLM，解析 tool_calls + content
  2. act(): 执行工具调用，处理结果

加上 Reflection Loop（自动修正）和 Stuck 检测。

生命周期:
  IDLE → THINKING → ACTING → THINKING → ... → FINISHED
                    ↘ ERROR
"""

import json
import threading
import time
import itertools
from pathlib import Path
from typing import List, Optional
from openai import OpenAI
from rich.console import Console
from rich.syntax import Syntax
from difflib import unified_diff

from kilee import config, theme
from kilee.pipeline.stage import Stage, register_stage
from kilee.pipeline.context import PipelineContext
from kilee.tools import dispatch_with_result, get_all_schemas
from kilee.schema import AgentState, ToolResult
from kilee.compressor import maybe_compress
from kilee.stuck import StuckDetector

console = Console(highlight=False)

# ── 配置常量 ─────────────────────────────────────────────────────────────────

MAX_REFLECTION_ATTEMPTS = 2
MAX_STEPS = 30


# ── Spinner ──────────────────────────────────────────────────────────────────

class Spinner:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        frames = itertools.cycle(theme.SPINNER_FRAMES)
        verbs  = itertools.cycle(theme.THINKING_VERBS)
        verb   = next(verbs)
        i = 0
        while not self._stop.is_set():
            f = next(frames)
            console.print(
                f"  [{theme.C['accent2']}]{f}[/] [{theme.C['dim']}]{verb}…[/]",
                end="\r",
            )
            time.sleep(0.12)
            i += 1
            if i % 8 == 0:
                verb = next(verbs)
        console.print(" " * 40, end="\r")

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()


# ── 工具调用显示 ────────────────────────────────────────────────────────────

def _tool_label(name: str, args: dict) -> str:
    """
    简洁的工具标签显示
    
    格式: [icon] [类型] 参数摘要
    """
    icon = theme.TOOL_ICONS.get(name, "⚙")
    ac, ac2, dm = theme.C["accent"], theme.C["accent2"], theme.C["dim"]
    
    if name == "execute_bash":
        cmd = args.get("command", "")
        if len(cmd) > 50:
            cmd = cmd[:47] + "…"
        return f"[{ac2}]{icon}[/]  [{dm}]{cmd}[/]"
    elif name == "fs_read":
        path = args.get("path", "")
        mode = args.get("mode", "Line")
        return f"[{ac2}]{icon}[/]  [{dm}]{path}[/] [{ac}]({mode})[/]"
    elif name == "fs_write":
        path = args.get("path", "")
        summ = args.get("summary", "")
        label = {"create": "➕", "str_replace": "✏",
                 "append": "➕", "insert": "✚"}.get(args.get("command",""), "")
        extra = f"  [{dm}]{summ}[/]" if summ else ""
        return f"[{ac2}]{icon}[/]  [{dm}]{path}[/] {label}{extra}"
    elif name == "save_memory":
        fact = args.get("fact", "")[:40]
        return f"[{ac2}]{icon}[/]  [{dm}]{fact}[/]"
    return f"[{ac2}]{icon}[/]  [{dm}]{name}[/]"


def _show_diff(path: str, old: str, new: str):
    diff = list(unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{Path(path).name}",
        tofile=f"b/{Path(path).name}",
        lineterm="",
    ))
    if diff:
        console.print(Syntax("".join(diff[:80]), "diff", theme="monokai",
                              background_color="default"))


def _print_tool_output(result: str, name: str):
    lines = result.splitlines()
    preview = lines[:12]
    if name in ("execute_bash", "fs_read"):
        text = "\n".join(preview)
        if text.strip():
            console.print(Syntax(text, "bash" if name == "execute_bash" else "text",
                                 theme="monokai", background_color="default",
                                 line_numbers=False))
    else:
        for line in preview:
            console.print(f"  [{theme.C['dim']}]{line}[/]")
    if len(lines) > 12:
        console.print(f"  [{theme.C['dim']}]… 共 {len(lines)} 行[/]")


# ── LLM Stage（Think→Act 循环） ─────────────────────────────────────────────

@register_stage
class LLMStage(Stage):
    """
    LLM 调用 Stage — Think→Act 循环
    
    工作流程:
      1. think(): 调用 LLM API，解析响应（content + tool_calls）
      2. act(): 执行所有工具调用
      3. 重复 think→act 直到 LLM 不再调用工具
      4. 内嵌 Reflection Loop（出错自动修正）
      5. Stuck 检测（重复模式自动调整策略）
    """

    def initialize(self, ctx: PipelineContext):
        cfg = config.load()
        self.client = OpenAI(api_key=cfg.get("api_key", ""), base_url=cfg["base_url"])
        self.cfg = cfg
        self.state = AgentState.IDLE
        self.current_step = 0
        self.reflection_count = 0
        self.stuck_detector = StuckDetector()  # OpenHands 风格卡住检测

    # ── Think ──────────────────────────────────────────────────────────

    async def think(self, ctx: PipelineContext) -> bool:
        """
        调用 LLM，解析响应
        
        Returns:
            True = 需要 act（有 tool_calls）
            False = 不需要 act（纯文本回复）
        """
        self.state = AgentState.THINKING

        with Spinner():
            response = self.client.chat.completions.create(
                model=self.cfg["model"],
                messages=ctx.messages,
                tools=get_all_schemas(),
                tool_choice="auto",
                max_tokens=self.cfg.get("max_tokens", 8192),
                stream=True,
            )
            chunks = list(response)

        full_content = ""
        tool_calls_map = {}
        finish_reason = None
        started = False

        for chunk in chunks:
            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason

            if delta.content:
                if not started:
                    console.print(f"  [{theme.C['accent']}]┃[/] ", end="")
                    started = True
                print(delta.content, end="", flush=True)
                full_content += delta.content

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    i = tc.index
                    if i not in tool_calls_map:
                        tool_calls_map[i] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_map[i]["id"] = tc.id
                    if tc.function.name:
                        tool_calls_map[i]["name"] = tc.function.name
                    if tc.function.arguments:
                        tool_calls_map[i]["arguments"] += tc.function.arguments

        if started:
            print()

        ctx.llm_response = full_content
        ctx.finish_reason = finish_reason

        has_tool_calls = bool(tool_calls_map) and finish_reason == "tool_calls"

        # 保存 tool_calls 到上下文供 act 使用
        if has_tool_calls:
            ctx._tool_calls_raw = list(tool_calls_map.values())

        # 添加 assistant 消息到对话
        tool_calls_list = None
        if has_tool_calls:
            tool_calls_list = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls_map.values()
            ]

        assistant_msg = {
            "role": "assistant",
            "content": full_content or None,
        }
        if tool_calls_list:
            assistant_msg["tool_calls"] = tool_calls_list
        ctx.messages.append(assistant_msg)

        return has_tool_calls

    # ── Act ────────────────────────────────────────────────────────────

    async def act(self, ctx: PipelineContext) -> bool:
        """
        执行工具调用
        
        Returns:
            True = 执行成功
            False = 执行失败
        """
        self.state = AgentState.ACTING
        tool_calls = getattr(ctx, "_tool_calls_raw", [])

        if not tool_calls:
            return False

        console.print()
        has_errors = False
        ctx.tool_results = []

        for tc in tool_calls:
            name = tc["name"]

            try:
                args = json.loads(tc["arguments"])
            except Exception:
                args = {}

            # 记录旧内容用于 diff
            old_content = None
            icon = theme.TOOL_ICONS.get(name, "⚙")
            if name == "fs_write" and args.get("command") == "str_replace":
                p = Path(args.get("path", "")).expanduser()
                if p.exists():
                    old_content = p.read_text(errors="replace")

            # 单行工具调用显示（执行中）
            console.print(
                f"  [{theme.C['accent2']}]{icon}[/] {_tool_label(name, args)}"
            )

            # 执行工具
            result = dispatch_with_result(name, args)
            ok = result.ok
            if not ok:
                has_errors = True

            # 覆盖显示完成状态
            status = f"[{theme.C['ok']}]✓[/]" if ok else f"[{theme.C['error']}]✗[/]"
            console.print(
                f"  {status} {_tool_label(name, args)}"
            )

            if not ok:
                console.print(f"    [{theme.C['error']}]{result.text}[/]")
            elif name == "fs_write" and old_content is not None:
                p = Path(args.get("path", "")).expanduser()
                if p.exists():
                    _show_diff(args.get("path", ""), old_content,
                               p.read_text(errors="replace"))
            elif name not in ("save_memory",) and result.output and result.output != "(无输出)":
                _print_tool_output(result.output, name)

            # 添加 tool 消息到对话
            ctx.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result.text,
            })
            ctx.tool_results.append({
                "name": name, "args": args,
                "result": result.text, "ok": ok,
            })

        console.print()

        # ── Stuck 检测（OpenHands 风格多模式检测） ─────────────────────
        for tr in ctx.tool_results:
            self.stuck_detector.record(tr["name"], tr["args"], tr["result"], tr["ok"])

        if self.stuck_detector.is_stuck():
            recovery = self.stuck_detector.get_recovery_prompt()
            console.print(f"  [{theme.C['warn']}]⚠ {self.stuck_detector.stuck_analysis.details}[/]")
            ctx.messages.append({"role": "user", "content": recovery})
            self.stuck_detector.clear()
            return True  # 继续循环

        # ── Reflection Loop ───────────────────────────────────────────
        if has_errors and self.reflection_count < MAX_REFLECTION_ATTEMPTS:
            self.reflection_count += 1
            error_details = [
                f"- {tr['name']}: {tr['result']}"
                for tr in ctx.tool_results if not tr['ok']
            ]
            if error_details:
                reflection_prompt = (
                    f"## 反思循环（第 {self.reflection_count}/{MAX_REFLECTION_ATTEMPTS} 轮）\n\n"
                    f"以下工具执行出错，请分析原因并修正：\n"
                    + "\n".join(error_details) +
                    "\n\n请决定如何修复——调整参数重试，或用其他方式替代。"
                )
                ctx.messages.append({"role": "user", "content": reflection_prompt})
                console.print(f"  [{theme.C['warn']}]⟳ reflection #{self.reflection_count}[/]")
                return True  # 继续循环

        # ── 自动压缩 ──────────────────────────────────────────────────
        total_chars = sum(len(str(m.get("content") or "")) for m in ctx.messages)
        if total_chars > 24000:
            new_msgs, did = maybe_compress(ctx.messages, console)
            if did:
                ctx.messages.clear()
                ctx.messages.extend(new_msgs)
                console.print(f"  [{theme.C['dim']}]☰ compressed[/]")

        return True  # 继续循环

    # ── Process（主入口） ─────────────────────────────────────────────

    def process(self, ctx: PipelineContext):
        """
        Think→Act 主循环
        
        循环: think → (有 tool_calls?) → act → think → ...
              → (纯文本回复) → 结束
        """
        self.state = AgentState.IDLE
        self.current_step = 0
        self.reflection_count = 0
        self._last_tool_names = []
        self._stuck_count = 0

        import asyncio

        while self.current_step < MAX_STEPS:
            self.current_step += 1

            # Think
            try:
                needs_act = asyncio.run(self.think(ctx))
            except Exception as e:
                console.print(f"  [{theme.C['error']}]✗ LLM 调用错误: {e}[/]")
                self.state = AgentState.ERROR
                break

            if not needs_act:
                # LLM 返回了纯文本回复，结束
                self.state = AgentState.FINISHED
                yield  # 让后续 Stage 处理
                return

            # Act
            try:
                should_continue = asyncio.run(self.act(ctx))
            except Exception as e:
                console.print(f"  [{theme.C['error']}]✗ 工具执行错误: {e}[/]")
                self.state = AgentState.ERROR
                break

            if not should_continue:
                break

        if self.current_step >= MAX_STEPS:
            console.print(f"  [{theme.C['warn']}]⚠ max steps ({MAX_STEPS})[/]")
            self.state = AgentState.FINISHED

        self.state = AgentState.FINISHED
        yield
