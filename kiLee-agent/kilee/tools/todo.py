"""Todo 工具 — 任务分解与进度追踪（借鉴 hermes-agent todo_tool）"""
from kilee.tools import ToolCategory

TOOL_CATEGORY = ToolCategory.SYSTEM
TOOL_METADATA = {"ephemeral": True}


import json
from typing import List, Dict, Any

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}

_store: List[Dict[str, str]] = []

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "todo",
        "description": (
            "管理任务列表。处理复杂多步骤任务时使用：先写入任务分解，执行过程中更新状态。"
            "不传 todos 参数则读取当前列表。"
            "每次开始复杂任务时调用，完成每个子任务后更新状态。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "任务列表，不传则只读取",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id":      {"type": "string", "description": "唯一ID，如 t1 t2"},
                            "content": {"type": "string", "description": "任务描述"},
                            "status":  {"type": "string", "enum": list(VALID_STATUSES)},
                        },
                        "required": ["id", "content", "status"],
                    },
                },
                "merge": {
                    "type": "boolean",
                    "description": "true=更新已有项，false=替换整个列表（默认false）",
                },
            },
        },
    },
}


def _run(todos: List[Dict] = None, merge: bool = False) -> str:
    global _store
    if todos is not None:
        if merge:
            existing = {item["id"]: item for item in _store}
            for t in todos:
                tid = str(t.get("id", "")).strip()
                if not tid:
                    continue
                status = t.get("status", "pending")
                if status not in VALID_STATUSES:
                    status = "pending"
                if tid in existing:
                    existing[tid] = {"id": tid, "content": t.get("content", existing[tid]["content"]), "status": status}
                else:
                    existing[tid] = {"id": tid, "content": t.get("content", ""), "status": status}
            _store = list(existing.values())
        else:
            _store = [{"id": str(t["id"]), "content": t["content"],
                       "status": t.get("status", "pending") if t.get("status") in VALID_STATUSES else "pending"}
                      for t in todos if t.get("id") and t.get("content")]

    if not _store:
        return "(任务列表为空)"

        STATUS_ICON = {"pending": "○", "in_progress": "◎", "completed": "✓", "cancelled": "✗"}
    lines = [f"{STATUS_ICON.get(t['status'], '○')} [{t['id']}] {t['content']} ({t['status']})" for t in _store]
    return "\n".join(lines)


tool_run = _run
run = _run
