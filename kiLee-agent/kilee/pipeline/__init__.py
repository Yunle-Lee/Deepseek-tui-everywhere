"""
Pipeline 管道系统（借鉴 AstrBot Stage 架构）

消息处理经过一系列 Stage，每个 Stage 可以 yield 实现洋葱模型：
前置处理 → yield → 后续Stage执行 → 后置处理

┌─────────────────────────────────────────────────────────────────┐
│ PipelineScheduler                                                │
│  ├─ Stage 1: InputStage     (解析用户输入)                       │
│  ├─ Stage 2: LLMStage      (调用 LLM + 工具调用)               │
│  │    └─ ReflectionLoop    (内嵌在 LLMStage 中)                 │
│  ├─ Stage 3: OutputStage   (格式化并显示响应)                   │
│  └─ Stage 4: MemoryStage   (更新记忆 + 自动压缩)               │
└─────────────────────────────────────────────────────────────────┘

相比 AstrBot 的优势：
- 终端场景简化版，不需要异步事件循环
- 洋葱模型保留，支持前后置拦截
- Stage 可插拔，按需注册
"""

from .stage import Stage, register_stage, registered_stages
from .scheduler import PipelineScheduler
from .context import PipelineContext

__all__ = ["Stage", "register_stage", "registered_stages", "PipelineScheduler", "PipelineContext"]
