"""
上下文压缩（OpenClaw 记忆管理 — 自动 & 手动双模式）

在 Agent 主循环中自动触发，也可通过 /compact 命令手动调用。

策略（借鉴 RDT / OpenMythos 的循环深度思想）：
  1. 保留 system prompt（Head）
  2. 保留最近的 N 轮对话（Tail）
  3. 中间部分由 LLM 压缩为结构化的摘要
  4. 摘要中包含 "已完成" / "进行中" / "重要信息" 三段
"""
from openai import OpenAI
from kilee import config

# token 粗估：1 token ≈ 4 字符
def _estimate_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
        total += len(str(content)) // 4
    # tool_calls 和 tool 消息也计入
    if m.get("tool_calls"):
        for tc in m["tool_calls"]:
            total += len(str(tc.get("function", {}).get("arguments", ""))) // 4
    return total


# 阈值配置
COMPRESS_THRESHOLD = 6000   # token 数超过此值触发压缩
KEEP_HEAD = 1               # 保留开头几条（system prompt）
KEEP_TAIL = 8               # 保留最近几条（比原来的6更多，保留更多上下文）

SUMMARY_PROMPT = """你是一个对话摘要助手。将以下对话历史压缩为简洁摘要。

要求：
1. 保留所有已完成的任务和结论
2. 记录未完成的工作（## 进行中的任务）
3. 记录重要的文件路径、变量名、决策、用户偏好
4. 不要回答对话中的问题，只做摘要
5. 保留工具调用的关键结果，但省略中间过程的细节

输出格式：
## 已完成
- ...

## 进行中的任务
- ...

## 重要信息
- ...
"""


def maybe_compress(messages: list, console=None) -> tuple[list, bool]:
    """如果超过阈值则压缩，返回 (新messages, 是否压缩了)"""
    estimated = _estimate_tokens(messages)
    if estimated < COMPRESS_THRESHOLD:
        return messages, False

    head = messages[:KEEP_HEAD]

    # 找到安全的 tail 起始点：不能从 tool 消息开头（其对应的 assistant tool_calls 会被截掉）
    tail_start = len(messages) - KEEP_TAIL
    while tail_start < len(messages):
        role = messages[tail_start].get("role")
        if role not in ("tool",) and not messages[tail_start].get("tool_calls"):
            break
        tail_start += 1
    tail_start = max(tail_start, KEEP_HEAD)

    tail = messages[tail_start:]
    middle = messages[KEEP_HEAD:tail_start]

    if not middle:
        return messages, False

    if console:
        console.print(f"[dim yellow]⟳ 上下文过长 ({estimated} tokens)，正在压缩...[/dim yellow]")

    # 用当前模型做摘要
    cfg = config.load()
    client = OpenAI(api_key=cfg.get("api_key", ""), base_url=cfg["base_url"])

    # 构造要压缩的中间内容
    middle_parts = []
    for m in middle:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            middle_parts.append(f"[{role}]: {content[:300]}")
        elif m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                middle_parts.append(f"[assistant→tool]: {fn.get('name', '?')}({fn.get('arguments', '')[:100]})")

    middle_text = "\n".join(middle_parts)

    if not middle_text.strip():
        return messages, False

    try:
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": middle_text},
            ],
            max_tokens=1500,
        )
        summary = resp.choices[0].message.content
    except Exception as e:
        if console:
            console.print(f"[dim red]✗ 压缩失败: {e}[/dim red]")
        return messages, False

    summary_msg = {
        "role": "system",
        "content": (
            "[CONTEXT COMPACTION] 以下是之前对话的摘要，作为背景参考，"
            "不要重复执行其中已完成的任务：\n\n" + summary
        ),
    }

    new_messages = head + [summary_msg] + tail
    saved = _estimate_tokens(messages) - _estimate_tokens(new_messages)
    if console:
        console.print(f"[dim green]✓ 压缩完成，{estimated} → {_estimate_tokens(new_messages)} tokens (节省 {saved})[/dim green]")

    return new_messages, True
