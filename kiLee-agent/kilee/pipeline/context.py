"""
Pipeline 上下文（借鉴 AstrBot PipelineContext）

在 Pipeline 的整个生命周期中共享的状态容器。
Stage 之间通过 context 传递数据。
"""

from typing import Any, Dict, List, Optional


class PipelineContext:
    """管道上下文——所有 Stage 共享的状态"""

    def __init__(self):
        # ── 输入 ──────────────────────────────────────────────────────
        self.user_input: str = ""
        """当前用户输入"""
        
        self.messages: List[Dict] = []
        """完整的对话消息列表（包含 system / user / assistant / tool）"""
        
        # ── 处理中 ────────────────────────────────────────────────────
        self.llm_response: str = ""
        """LLM 的文本回复"""
        
        self.tool_results: List[Dict] = []
        """本轮工具调用结果 [{name, args, result, ok}]"""
        
        self.finish_reason: Optional[str] = None
        """LLM 响应结束原因：stop / tool_calls / length"""
        
        # ── 控制 ──────────────────────────────────────────────────────
        self._stopped: bool = False
        """是否停止管道继续执行"""
        
        # ── 元数据 ────────────────────────────────────────────────────
        self.extras: Dict[str, Any] = {}
        """扩展字段，供自定义 Stage 使用"""

    def stop(self):
        """停止管道继续执行后续 Stage"""
        self._stopped = True

    @property
    def is_stopped(self) -> bool:
        return self._stopped
