"""
from kilee.tools import ToolCategory

TOOL_CATEGORY = ToolCategory.MEMORY
TOOL_METADATA = {"persistent": True}


记忆系统（OpenClaw 三级记忆架构）

层级结构:
  L1 - 工作记忆（Working Memory）：当前对话上下文，存储在 messages 中
  L2 - 长期记忆（Long-term Memory）：跨会话持久化，存储在 ~/.kilee/memory.json
  L3 - 项目记忆（Project Memory）：项目级 KILEE.md / CLAUDE.md 静态注入

本模块管理 L2（长期记忆），L1 由 agent.run 管理，L3 由 _load_project_context 管理。

增强功能（v0.2）:
  - 事实去重增强（相似内容检测）
  - 时间戳记录每条记忆
  - 支持 /memory search <keyword> 搜索记忆
  - 支持 /memory stats 查看统计
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

MEMORY_FILE = os.path.expanduser("~/.kilee/memory.json")
MAX_FACTS = 100  # 最多保留100条记忆


def _load() -> dict:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"facts": [], "updated_at": None}


def _save(data: dict):
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    data["updated_at"] = datetime.now().isoformat()
    # 限制记忆数量
    if len(data.get("facts", [])) > MAX_FACTS:
        data["facts"] = data["facts"][-MAX_FACTS:]
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _similar_to_existing(fact: str, existing_facts: list) -> bool:
    """检查新事实是否与已有事实相似（去重增强）"""
    fact_lower = fact.lower().strip()
    for existing in existing_facts:
        # 完全匹配
        if existing.lower().strip() == fact_lower:
            return True
        # 一方的核心信息被另一方包含
        if len(fact) > 15 and fact_lower in existing.lower():
            return True
        if len(existing) > 15 and existing.lower() in fact_lower:
            return True
    return False


def get_context() -> str:
    """返回注入系统提示的记忆块"""
    data = _load()
    facts = data.get("facts", [])
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts[-30:])  # 最多30条
    return f"<memory-context>\n[关于用户的已知信息]\n{lines}\n</memory-context>"


def save_fact(fact: str):
    data = _load()
    # 增强去重
    if not _similar_to_existing(fact, data["facts"]):
        data["facts"].append(fact)
    _save(data)


def clear():
    _save({"facts": []})


def list_facts() -> list:
    return _load().get("facts", [])


def search_facts(keyword: str) -> list:
    """搜索记忆中的事实（/memory search 支持）"""
    facts = list_facts()
    if not keyword:
        return facts
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    return [f for f in facts if pattern.search(f)]


def get_stats() -> dict:
    """记忆统计"""
    data = _load()
    facts = data.get("facts", [])
    return {
        "total": len(facts),
        "updated_at": data.get("updated_at", "never"),
        "max": MAX_FACTS,
    }


# ── 工具规范 ─────────────────────────────────────────────────────────────────
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "保存关于用户的重要信息到持久记忆，跨会话可用。用于记住用户偏好、项目信息、重要事实等。",
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "要记住的信息，一句话描述"},
            },
            "required": ["fact"],
        },
    },
}


def tool_run(fact: str) -> str:
    save_fact(fact)
    return f"已记住: {fact}"


run = tool_run
