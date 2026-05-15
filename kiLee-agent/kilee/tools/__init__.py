"""
工具注册系统（借鉴 browser-use Registry + Hermes 自注册）

双模式支持：
  1. 装饰器模式（推荐）: @register_tool(name, desc, ...) 装饰函数
  2. 自动发现模式（兼容）: 自动发现 TOOL_SCHEMA + tool_run

v0.5 增强（借鉴 browser-use Registry）:
  - @register_tool 装饰器，一键注册
  - 上下文注入：工具可获取 context（messages/state）
  - 参数自动提取：从函数签名自动生成 schema
"""

import functools
import importlib
import inspect
import pkgutil
import os
from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints

# ── 工具注册表 ──────────────────────────────────────────────────────────────
_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}
"""{tool_name: {"schema": dict, "fn": callable, "module": str, "category": str, "metadata": dict}}"""


# ── 预定义分类 ──────────────────────────────────────────────────────────────

class ToolCategory:
    """工具分类"""
    SYSTEM = "system"
    FILESYSTEM = "filesystem"
    EXECUTION = "execution"
    MEMORY = "memory"
    COMMUNICATION = "communication"
    UTILITY = "utility"
    CUSTOM = "custom"

    @classmethod
    def get_all(cls) -> list:
        return [v for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, str)]


# ── 类型映射 ────────────────────────────────────────────────────────────────

_TYPE_MAP = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array", "items": {"type": "string"}},
    dict: {"type": "object"},
    Optional[str]: {"type": "string"},
    Optional[int]: {"type": "integer"},
}


def _py_type_to_json_schema(py_type) -> dict:
    """Python 类型 → JSON Schema（借鉴 browser-use _create_param_model）"""
    origin = getattr(py_type, "__origin__", None)
    if origin is Union:  # noqa: F811
        args = py_type.__args__
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _py_type_to_json_schema(non_none[0])
        return {"type": "string"}
    
    if py_type in _TYPE_MAP:
        return _TYPE_MAP[py_type]
    
    # 处理 Optional[X]
    if hasattr(py_type, "__args__"):
        args = py_type.__args__
        for arg in args:
            if arg is not type(None) and arg in _TYPE_MAP:
                return _TYPE_MAP[arg]
    
    return {"type": "string"}


# ── 装饰器注册（推荐方式） ─────────────────────────────────────────────────

def register_tool(
    name: Optional[str] = None,
    description: str = "",
    category: str = ToolCategory.UTILITY,
    metadata: Optional[dict] = None,
):
    """
    装饰器：将一个函数注册为工具（借鉴 browser-use @registry.action）
    
    用法:
        @register_tool(name="my_tool", description="...")
        def my_tool(param1: str, param2: int = 0) -> str:
            ...
    
    参数从函数签名自动提取，自动生成 JSON Schema。
    支持一个特殊参数 context: dict，会自动注入当前上下文。
    """
    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        hints = get_type_hints(func) if hasattr(func, "__module__") else {}
        
        # 构建参数 schema
        properties = {}
        required = []
        has_context_param = False
        
        for param_name, param in sig.parameters.items():
            if param_name == "context":
                has_context_param = True
                continue  # context 是注入参数，不暴露给 LLM
            
            py_type = hints.get(param_name, str)
            schema = _py_type_to_json_schema(py_type)
            
            if param.annotation and param.annotation != inspect.Parameter.empty:
                # 检查是否有 docstring 描述
                desc = ""
                if func.__doc__:
                    for line in func.__doc__.split("\n"):
                        stripped = line.strip()
                        if stripped.startswith(f"{param_name}:"):
                            desc = stripped.split(":", 1)[1].strip()
                            break
                if desc:
                    schema["description"] = desc
            
            properties[param_name] = schema
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        tool_name = name or func.__name__
        tool_description = description or (func.__doc__ or "").split("\n")[0].strip()
        
        schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }
        if required:
            schema["function"]["parameters"]["required"] = required
        
        # 包装函数：注入 context 参数
        @functools.wraps(func)
        def wrapped(**kwargs):
            # 如果原函数需要 context 但没传，注入空 dict
            if has_context_param and "context" not in kwargs:
                kwargs["context"] = {}
            return func(**kwargs)
        
        # 注册到注册表
        module_name = func.__module__ if hasattr(func, "__module__") else "decorated"
        _TOOL_REGISTRY[tool_name] = {
            "schema": schema,
            "fn": wrapped,
            "module": module_name.split(".")[-1],
            "category": category,
            "metadata": metadata or {},
            "has_context_param": has_context_param,
        }
        
        return wrapped
    
    return decorator


# ── 自动发现模式（兼容旧版） ────────────────────────────────────────────────

def is_tool_module(mod_name: str) -> bool:
    if mod_name.startswith("_"):
        return False
    return True


def discover_tools():
    """扫描 tools/ 目录，自动注册旧式工具模块"""
    pkg_path = os.path.dirname(__file__)

    for importer, modname, ispkg in pkgutil.iter_modules([pkg_path]):
        if not is_tool_module(modname):
            continue

        module = importlib.import_module(f"kilee.tools.{modname}")

        # 支持两种模式：
        schema = getattr(module, "TOOL_SCHEMA", getattr(module, "SCHEMA", None))
        run_fn = getattr(module, "tool_run", getattr(module, "run", None))

        if schema is None or run_fn is None:
            continue

        name = schema.get("function", {}).get("name", modname)
        
        # 如果已经被装饰器注册过，跳过
        if name in _TOOL_REGISTRY:
            continue

        category = getattr(module, "TOOL_CATEGORY", ToolCategory.UTILITY)
        metadata = getattr(module, "TOOL_METADATA", {})

        _TOOL_REGISTRY[name] = {
            "schema": schema,
            "fn": run_fn,
            "module": modname,
            "category": category,
            "metadata": metadata,
            "has_context_param": False,
        }


# ── 公共 API ────────────────────────────────────────────────────────────────

def get_all_schemas() -> List[Dict]:
    if not _TOOL_REGISTRY:
        discover_tools()
    return [info["schema"] for info in _TOOL_REGISTRY.values()]


def get_tool_names() -> List[str]:
    if not _TOOL_REGISTRY:
        discover_tools()
    return list(_TOOL_REGISTRY.keys())


def get_tools_by_category(category: str) -> List[Dict]:
    if not _TOOL_REGISTRY:
        discover_tools()
    return [
        {"name": name, **info}
        for name, info in _TOOL_REGISTRY.items()
        if info.get("category") == category
    ]


def get_tool_info(name: str) -> Optional[Dict]:
    if not _TOOL_REGISTRY:
        discover_tools()
    info = _TOOL_REGISTRY.get(name)
    if info:
        return {"name": name, **info}
    return None


def dispatch(name: str, args: dict) -> str:
    if not _TOOL_REGISTRY:
        discover_tools()
    info = _TOOL_REGISTRY.get(name)
    if info is None:
        return f"[ERROR] 未知工具: {name}"
    try:
        result = info["fn"](**args)
        from kilee.schema import ToolResult
        if isinstance(result, ToolResult):
            return result.text
        return str(result)
    except Exception as e:
        return f"[ERROR] 工具 {name} 执行出错: {e}"


def dispatch_with_result(name: str, args: dict, context: Optional[dict] = None) -> "ToolResult":
    """增强版 dispatch：支持上下文注入（借鉴 browser-use SpecialActionParameters）"""
    from kilee.schema import ToolResult
    if not _TOOL_REGISTRY:
        discover_tools()
    info = _TOOL_REGISTRY.get(name)
    if info is None:
        return ToolResult.failure(f"未知工具: {name}")
    try:
        # 如果工具需要 context 且提供了，注入
        if info.get("has_context_param") and context:
            args["context"] = context
        result = info["fn"](**args)
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, str) and (result.startswith("[ERROR]") or result.startswith("[BLOCKED]")):
            return ToolResult.failure(result)
        return ToolResult.success(str(result))
    except Exception as e:
        return ToolResult.failure(f"工具 {name} 执行出错: {e}")


def reload_tools():
    _TOOL_REGISTRY.clear()
    discover_tools()


# 首次加载时自动发现
discover_tools()

