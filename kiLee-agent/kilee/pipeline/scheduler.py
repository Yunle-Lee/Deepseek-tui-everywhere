"""
Pipeline 调度器（借鉴 AstrBot PipelineScheduler）

负责按注册顺序执行所有 Stage，支持洋葱模型。
"""

from typing import List, Optional
from .stage import Stage, registered_stages
from .context import PipelineContext


class PipelineScheduler:
    """
    管道调度器
    
    用法：
        scheduler = PipelineScheduler()
        scheduler.register(MyStage)
        scheduler.run(ctx)
    """

    def __init__(self):
        self.stages: List[Stage] = []

    def register(self, stage_cls: type[Stage]):
        """注册一个 Stage 类"""
        instance = stage_cls()
        self.stages.append(instance)

    def register_all(self):
        """注册所有已通过 @register_stage 装饰的 Stage"""
        for stage_cls in registered_stages:
            instance = stage_cls()
            self.stages.append(instance)

    def initialize(self, ctx: PipelineContext):
        """初始化所有已注册的 Stage"""
        for stage in self.stages:
            stage.initialize(ctx)

    def run(self, ctx: PipelineContext):
        """
        执行 Pipeline（同步版洋葱模型）
        
        按注册顺序依次执行每个 Stage 的 process()。
        如果某个 Stage yield，则递归进入后续 Stage。
        """
        self._process_stages(ctx, 0)

    def _process_stages(self, ctx: PipelineContext, from_index: int):
        """递归执行 Stage 链"""
        for i in range(from_index, len(self.stages)):
            if ctx.is_stopped:
                break

            stage = self.stages[i]
            gen = stage.process(ctx)

            # 检查是否是生成器（即是否 yield）
            if hasattr(gen, "__next__"):
                try:
                    next(gen)  # 执行前置处理直到 yield
                    # 递归执行后续 Stage
                    self._process_stages(ctx, i + 1)
                    # 后置处理
                    try:
                        next(gen)
                    except StopIteration:
                        pass
                except StopIteration:
                    pass
            # 如果不是生成器（没有 yield），则继续下一个 Stage
