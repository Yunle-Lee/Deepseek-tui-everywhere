import os
import sys
import click
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from kilee import config, theme
from kilee.agent import run_agent, build_system_prompt, print_welcome, get_client
from kilee.tools import memory as mem_tool, get_tool_names
from kilee.compressor import maybe_compress

console = Console(highlight=False)
HISTORY_FILE = os.path.expanduser("~/.kilee/history")

PROMPT_STYLE = Style.from_dict({"prompt": "#7C3AED bold"})

SLASH_HELP = [
    ("/clear",        "clear conversation history"),
    ("/compact",      "compress context"),
    ("/memory",            "view persistent memory"),
    ("/memory clear",      "wipe all memory"),
    ("/memory search kw",  "search memory by keyword"),
    ("/memory stats",      "show memory statistics"),
    ("/model [name]", "view / switch model"),
    ("/tips",         "show random usage tips"),
    ("/help",         "show this help"),
    ("/exit",         "quit"),
]

_AC  = theme.C["accent"]
_AC2 = theme.C["accent2"]
_DM  = theme.C["dim"]
_OK  = theme.C["ok"]
_ERR = theme.C["error"]
_WRN = theme.C["warn"]
_INF = theme.C["info"]
_H1  = theme.C["h1"]
_H2  = theme.C["h2"]

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """KiLee - DeepSeek 驱动的终端 AI Agent"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)

@cli.command()
def chat():
    """与 KiLee 对话"""
    cfg = config.load()
    if not cfg.get("api_key"):
        from kilee.setup import run_setup
        run_setup()
        cfg = config.load()
        if not cfg.get("api_key"):
            sys.exit(1)

    print_welcome()
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)

    messages = [{"role": "system", "content": build_system_prompt()}]
    session = PromptSession(
        history=FileHistory(HISTORY_FILE),
        style=PROMPT_STYLE,
        mouse_support=False,
    )

    while True:
        try:
            user_input = session.prompt(HTML(f"<style fg='#00BFBF'><b>{theme.PROMPT_SYMBOL}</b></style>")).strip()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[{_DM}]bye[/]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            _handle_slash(user_input, messages)
            if user_input.lower() in ("/exit", "/quit"):
                break
            continue

        # 用户消息：gemini-cli 风格 "> " 前缀
        console.print(f"\n[{_AC}]>[/] {user_input}\n")

        messages.append({"role": "user", "content": user_input})
        try:
            run_agent(messages)
        except KeyboardInterrupt:
            console.print(f"\n[{_DM}]已中断[/]")
        except Exception as e:
            console.print(f"\n[{_ERR}]错误: {e}[/]")

        total_chars = sum(len(str(m.get("content") or "")) for m in messages)
        console.print(f"\n  [{_DM}]─ {total_chars//4} tokens[/]")

def _handle_slash(cmd_str: str, messages: list):
    parts = cmd_str.split()
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit"):
        console.print(f"[{_DM}]bye[/]")

    elif cmd == "/clear":
        messages.clear()
        messages.append({"role": "system", "content": build_system_prompt()})
        console.print(f"  [{_DM}]对话已清空[/]")

    elif cmd == "/compact":
        new_msgs, did = maybe_compress(messages, console)
        if did:
            messages.clear()
            messages.extend(new_msgs)
        else:
            console.print(f"  [{_DM}]上下文较短，无需压缩[/]")

    elif cmd == "/memory":
        if len(parts) > 1 and parts[1] == "clear":
            mem_tool.clear()
            console.print(f"  [{_DM}]记忆已清除[/]")
        elif len(parts) > 1 and parts[1] == "search":
            keyword = " ".join(parts[2:])
            if not keyword:
                console.print(f"  [{_DM}]用法: /memory search <关键词>[/]")
            else:
                results = mem_tool.search_facts(keyword)
                if results:
                    console.print(f"  [{_AC2}]搜索 '{keyword}' 找到 {len(results)} 条:[/]")
                    for i, f in enumerate(results, 1):
                        console.print(f"  [{_AC2}]{i}.[/] [{_DM}]{f}[/]")
                else:
                    console.print(f"  [{_DM}]未找到匹配 '{keyword}' 的记忆[/]")
        elif len(parts) > 1 and parts[1] == "stats":
            stats = mem_tool.get_stats()
            console.print(f"  [{_AC2}]记忆统计:[/]")
            console.print(f"  [{_DM}]  总数: [/][{_AC}]{stats['total']}[/]")
            console.print(f"  [{_DM}]  上限: [/][{_AC}]{stats['max']}[/]")
            console.print(f"  [{_DM}]  更新: [/][{_DM}]{stats['updated_at']}[/]")
        else:
            facts = mem_tool.list_facts()
            if facts:
                for i, f in enumerate(facts, 1):
                    console.print(f"  [{_AC2}]{i}.[/] [{_DM}]{f}[/]")
            else:
                console.print(f"  [{_DM}]暂无记忆[/]")

    elif cmd == "/tips":
        from kilee.tips import TIPS
        import random
        for tip in random.sample(TIPS, min(5, len(TIPS))):
            console.print(f"  [{_AC}]◈[/] [{_DM}]{tip}[/]")

    elif cmd == "/model":
        if len(parts) > 1:
            config.set_value("model", parts[1])
            console.print(f"  [{_DM}]模型已切换: {parts[1]}[/]")
        else:
            cfg = config.load()
            console.print(f"  [{_AC}]当前:[/] [{_AC2}]{cfg['model']}[/]")
            console.print(f"  [{_DM}]可用: deepseek-chat  deepseek-reasoner[/]")

    elif cmd == "/help":
        console.print(f"  [{_AC}]commands[/]")
        for c, d in SLASH_HELP:
            console.print(f"    [{_H2}]{c:<20}[/] [{_DM}]{d}[/]")

    else:
        console.print(f"  [{_DM}]未知命令: {cmd}  输入 /help 查看[/]")


@cli.command()
@click.argument("text", nargs=-1)
def translate(text):
    """自然语言转 shell 命令"""
    cfg = config.load()
    if not cfg.get("api_key"):
        console.print(f"[{_ERR}]未设置 API Key，请先运行: kilee login[/]")
        sys.exit(1)
    query = " ".join(text) or click.prompt(theme.PROMPT_SYMBOL)
    client, cfg = get_client()
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": "将用户描述转为shell命令。只输出命令本身，不加任何解释或代码块。"},
            {"role": "user", "content": query},
        ],
    )
    cmd = resp.choices[0].message.content.strip()
    console.print(f"\n  [{_AC}]$ {cmd}[/]\n")
    if click.confirm("  执行？", default=False):
        import subprocess
        subprocess.run(cmd, shell=True)

@cli.command()
def setup():
    """Run the interactive setup wizard"""
    from kilee.setup import run_setup
    run_setup()

@cli.command()
def login():
    """设置 DeepSeek API Key"""
    key = click.prompt("API Key", hide_input=True)
    config.set_value("api_key", key)
    console.print(f"  [{_DM}]已保存[/]")

@cli.command()
def logout():
    config.set_value("api_key", "")
    console.print(f"  [{_DM}]已登出[/]")

@cli.command()
def whoami():
    cfg = config.load()
    console.print(f"  [{_DM}]model[/]    [{_AC}]{cfg['model']}[/]")
    console.print(f"  [{_DM}]api_key[/]  [{_AC2}]{'已设置' if cfg.get('api_key') else '未设置'}[/]")
    console.print(f"  [{_DM}]base_url[/] [{_DM}]{cfg['base_url']}[/]")

@cli.command()
def doctor():
    import shutil
    checks = [
        ("python 3.10+", sys.version_info >= (3, 10)),
        ("api key",      bool(config.get("api_key"))),
        ("curl",         bool(shutil.which("curl"))),
        ("git",          bool(shutil.which("git"))),
    ]
    for name, ok in checks:
        mark = f"[{_OK}]✓[/]" if ok else f"[{_ERR}]✗[/]"
        console.print(f"  {mark}  [{_DM}]{name}[/]")

@cli.command()
def settings():
    import json
    cfg = {k: v for k, v in config.load().items() if k != "api_key"}
    console.print_json(json.dumps(cfg, ensure_ascii=False, indent=2))

@cli.command()
def telegram():
    """Start the Telegram bot bridge"""
    from kilee.integrations.telegram import run_bot
    run_bot()

@cli.command()
def feishu():
    """Start the Feishu/Lark bot bridge"""
    from kilee.integrations.feishu import run_bot
    run_bot()

if __name__ == "__main__":
    cli()
