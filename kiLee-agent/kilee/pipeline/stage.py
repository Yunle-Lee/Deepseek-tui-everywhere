"""
Pipeline Stage 基类（借鉴 AstrBot Stage 架构）

Stage 实现洋葱模型：
  前置处理 → yield → 后续 Stage 执行 → 后置处理
"""

from typing import Generator, Optional

# 全局 Stage 注册表
registered_stages: list[type["Stage"]] = []


def register_stage(cls):
    """装饰器：将 Stage 实现类注册到全局注册表"""
    registered_stages.append(cls)
    return cls


class Stage:
    """管道阶段基类"""

    def initialize(self, ctx: "PipelineContext"):
        """初始化阶段（在管道启动时调用）"""
        pass

    def process(self, ctx: "PipelineContext") -> Generator[None, None, None]:
        """
        处理阶段核心方法。
        
        使用 yield 实现洋葱模型：
        - yield 之前的代码是"前置处理"
        - yield 暂停，让后续 Stage 执行
        - yield 恢复后是"后置处理"
        
        如果不 yield，则不进入后续 Stage（终止管道）
        """
        yield
