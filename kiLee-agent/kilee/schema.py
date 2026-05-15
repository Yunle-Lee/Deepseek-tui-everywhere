"""
KiLee 数据模型（借鉴 OpenManus schema）

核心数据结构：
- AgentState: Agent 状态机
- Message: 统一消息格式
- ToolCall: 工具调用封装
- AgentContext: Agent 运行上下文
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Agent 状态机 ────────────────────────────────────────────────────────────

class AgentState(str, Enum):
    """Agent 生命周期状态（借鉴 OpenManus AgentState）
    
    IDLE → THINKING → ACTING → FINISHED
                    ↘ ERROR ↗
    """
    IDLE = "idle"              # 空闲，等待输入
    THINKING = "thinking"      # LLM 思考中
    ACTING = "acting"          # 执行工具调用
    FINISHED = "finished"      # 任务完成
    ERROR = "error"            # 出错


# ── 消息模型 ────────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """工具调用封装（借鉴 OpenManus ToolCall）"""
    id: str
    name: str
    arguments: str  # JSON string
    index: int = 0


@dataclass
class Message:
    """统一消息格式"""
    role: str  # system / user / assistant / tool
    content: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict:
        """转 OpenAI 消息格式"""
        msg = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg

    @classmethod
    def system_message(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user_message(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant_message(cls, content: str) -> "Message":
        return cls(role="assistant", content=content)

    @classmethod
    def tool_message(cls, content: str, tool_call_id: str, name: str = "") -> "Message":
        return cls(role="tool", content=content, tool_call_id=tool_call_id, name=name)

    @classmethod
    def from_tool_calls(cls, content: Optional[str], tool_calls: List[Dict]) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls)


# ── ToolResult ──────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """标准工具返回格式（借鉴 OpenManus ToolResult）
    
    统一所有工具的返回格式，支持:
    - output: 正常输出文本
    - error: 错误信息
    - base64_image: 图片数据（预留）
    """
    output: Optional[str] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def text(self) -> str:
        if self.error:
            return f"[ERROR] {self.error}"
        return self.output or ""

    def __bool__(self):
        return self.output is not None or self.error is not None

    def __str__(self):
        return self.text

    @classmethod
    def success(cls, output: str) -> "ToolResult":
        return cls(output=output)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(error=error)
