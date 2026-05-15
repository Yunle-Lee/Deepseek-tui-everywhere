"""
增强工具规范（借鉴 AstrBot FunctionTool + ToolSet）

相比 tools/__init__.py 的自注册系统，这里提供：
1. FunctionTool 类：带分类、优先级、上下文的增强工具定义
2. ToolSet 类：管理工具集合，支持多厂商 schema 转换
3. 向后兼容：自动包装现有的 TOOL_SCHEMA + tool_run 工具
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ── 工具分类枚举 ─────────────────────────────────────────────────────────────

class ToolCategory:
    """工具分类（借鉴 AstrBot Star 插件的分类思想）"""
    SYSTEM = "system"        # 系统核心工具
    FILESYSTEM = "filesystem"  # 文件操作
    EXECUTION = "execution"    # 命令执行
    MEMORY = "memory"         # 记忆相关
    COMMUNICATION = "communication"  # 通信（搜索、clarify）
    UTILITY = "utility"       # 工具类
    CUSTOM = "custom"         # 用户自定义


# ── FunctionTool ─────────────────────────────────────────────────────────────

@dataclass
class FunctionTool:
    """
    增强工具定义（借鉴 AstrBot FunctionTool）
    
    相比旧的 TOOL_SCHEMA dict，增加：
    - category: 工具分类
    - priority: 优先级（影响显示顺序）
    - builtin: 是否内置工具
    - handler: 处理函数（兼容旧的 tool_run）
    """
    name: str
    description: str = ""
    parameters: Dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    category: str = ToolCategory.UTILITY
    priority: int = 0
    builtin: bool = True
    handler: Optional[Callable] = None

    def to_openai_schema(self) -> Dict:
        """转换为 OpenAI function calling schema"""
        result = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
        return result

    def to_anthropic_schema(self) -> Dict:
        """转换为 Anthropic API tool schema"""
        input_schema = {"type": "object"}
        if self.parameters:
            input_schema["properties"] = self.parameters.get("properties", {})
            input_schema["required"] = self.parameters.get("required", [])
        result = {
            "name": self.name,
            "input_schema": input_schema,
        }
        if self.description:
            result["description"] = self.description
        return result

    def to_google_schema(self) -> Dict:
        """转换为 Google GenAI function declaration"""
        result = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.parameters:
            result["parameters"] = self.parameters
        return result

    def call(self, **kwargs) -> str:
        """调用工具 handler"""
        if self.handler:
            return self.handler(**kwargs)
        return f"[ERROR] 工具 {self.name} 没有注册 handler"


# ── ToolSet ──────────────────────────────────────────────────────────────────

class ToolSet:
    """
    工具集合（借鉴 AstrBot ToolSet）
    
    管理一组 FunctionTool，支持：
    - 添加/移除/查找
    - 多厂商 schema 转换（OpenAI / Anthropic / Google）
    - 合并其他 ToolSet
    """

    def __init__(self):
        self._tools: Dict[str, FunctionTool] = {}

    def add(self, tool: FunctionTool):
        """添加或覆盖工具"""
        self._tools[tool.name] = tool

    def remove(self, name: str):
        """移除工具"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[FunctionTool]:
        """按名称获取工具"""
        return self._tools.get(name)

    def list(self) -> List[FunctionTool]:
        """获取所有工具列表（按优先级排序）"""
        return sorted(self._tools.values(), key=lambda t: (-t.priority, t.name))

    def names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())

    def merge(self, other: "ToolSet"):
        """合并另一个 ToolSet"""
        for tool in other._tools.values():
            self.add(tool)

    def filter_by_category(self, category: str) -> List[FunctionTool]:
        """按分类过滤"""
        return [t for t in self._tools.values() if t.category == category]

    # ── 多厂商 Schema ─────────────────────────────────────────────────

    def openai_schemas(self) -> List[Dict]:
        """获取 OpenAI 格式的 tool schemas"""
        return [t.to_openai_schema() for t in self.list()]

    def anthropic_schemas(self) -> List[Dict]:
        """获取 Anthropic 格式的 tool schemas"""
        return [t.to_anthropic_schema() for t in self.list()]

    def google_schemas(self) -> List[Dict]:
        """获取 Google GenAI 格式的 tool schemas"""
        declarations = [t.to_google_schema() for t in self.list()]
        return {"function_declarations": declarations}

    def __len__(self):
        return len(self._tools)

    def __bool__(self):
        return len(self._tools) > 0

    def __iter__(self):
        return iter(self.list())


# ── 工厂函数：从旧 Schema 构建 FunctionTool ──────────────────────────────────

def from_legacy_schema(schema: Dict, handler: Callable) -> FunctionTool:
    """
    从旧的 TOOL_SCHEMA dict 构建 FunctionTool（向后兼容）
    
    Args:
        schema: 旧的 TOOL_SCHEMA 格式
        handler: tool_run 函数
    
    Returns:
        FunctionTool 实例
    """
    func = schema.get("function", {})
    return FunctionTool(
        name=func.get("name", "unknown"),
        description=func.get("description", ""),
        parameters=func.get("parameters", {"type": "object", "properties": {}}),
        category=ToolCategory.CUSTOM,
        handler=handler,
    )


def build_toolset_from_registry() -> ToolSet:
    """
    从自注册系统中构建完整的 ToolSet
    
    自动发现所有已注册的工具并转换为 FunctionTool
    """
    from kilee.tools import _TOOL_REGISTRY, discover_tools

    if not _TOOL_REGISTRY:
        discover_tools()

    toolset = ToolSet()
    for name, info in _TOOL_REGISTRY.items():
        schema = info["schema"]
        fn = info["fn"]
        ft = from_legacy_schema(schema, fn)
        toolset.add(ft)

    return toolset
