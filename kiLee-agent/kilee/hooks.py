"""
Agent Hooks 钩子系统（借鉴 AstrBot Agent Hooks）

允许外部代码在 Agent 运行的各个生命周期点注入自定义逻辑。

用法：
```python
class MyHooks(BaseHooks):
    def on_tool_call(self, name, args):
        console.print(f"调用工具: {name}")
    
    def on_llm_response(self, content):
        console.print(f"收到回复: {content[:50]}...")

hooks = HooksManager()
hooks.register(MyHooks())
```
"""

from typing import Any, Dict, List, Optional, Type


class BaseHooks:
    """钩子基类——继承并重写需要的方法"""

    def on_llm_request(self, messages: List[Dict]) -> None:
        """LLM 请求前触发"""
        pass

    def on_llm_response(self, content: str) -> None:
        """LLM 返回文本响应后触发"""
        pass

    def on_tool_call(self, name: str, args: Dict) -> None:
        """工具调用前触发"""
        pass

    def on_tool_result(self, name: str, args: Dict, result: str, ok: bool) -> None:
        """工具调用完成后触发"""
        pass

    def on_error(self, name: str, error: str) -> None:
        """工具执行出错时触发"""
        pass

    def on_reflection(self, attempt: int, max_attempts: int) -> None:
        """反思循环触发时调用"""
        pass

    def on_compress(self, before_tokens: int, after_tokens: int) -> None:
        """上下文压缩后触发"""
        pass


class HooksManager:
    """
    钩子管理器——管理多个 Hooks 实现
    
    类似 AstrBot 的 event hooks 机制，但更轻量。
    所有注册的 Hooks 会被依次调用。
    """

    def __init__(self):
        self._hooks: List[BaseHooks] = []

    def register(self, hooks: BaseHooks):
        """注册一个 Hooks 实现"""
        self._hooks.append(hooks)

    def unregister(self, hooks: BaseHooks):
        """取消注册"""
        self._hooks.remove(hooks)

    def clear(self):
        """清除所有 Hooks"""
        self._hooks.clear()

    # ── 事件触发 ──────────────────────────────────────────────────────

    def on_llm_request(self, messages: List[Dict]):
        for h in self._hooks:
            h.on_llm_request(messages)

    def on_llm_response(self, content: str):
        for h in self._hooks:
            h.on_llm_response(content)

    def on_tool_call(self, name: str, args: Dict):
        for h in self._hooks:
            h.on_tool_call(name, args)

    def on_tool_result(self, name: str, args: Dict, result: str, ok: bool):
        for h in self._hooks:
            h.on_tool_result(name, args, result, ok)

    def on_error(self, name: str, error: str):
        for h in self._hooks:
            h.on_error(name, error)

    def on_reflection(self, attempt: int, max_attempts: int):
        for h in self._hooks:
            h.on_reflection(attempt, max_attempts)

    def on_compress(self, before_tokens: int, after_tokens: int):
        for h in self._hooks:
            h.on_compress(before_tokens, after_tokens)


# ── 全局单例 ─────────────────────────────────────────────────────────────────
_global_hooks = HooksManager()


def get_hooks() -> HooksManager:
    """获取全局 Hooks 管理器"""
    return _global_hooks
