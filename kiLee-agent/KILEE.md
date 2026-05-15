# Project Context — KiLee Agent

> This file is automatically loaded by KiLee as static context (Harness Engineering - Context Engineering).

## Architecture (v0.3 — Pipeline 四层架构)

```
CLI 层        main.py (click CLI, slash commands)
├─ Agent 层   agent.py (Pipeline 调度入口)
│  ├─ Pipeline  pipeline/ (Stage 洋葱模型调度器)
│  │  ├─ LLMStage   LLM 调用 + 工具调用 + Reflection Loop
│  │  └─ ...        可扩展更多 Stage
│  └─ Hooks     hooks.py (事件钩子系统)
├─ Tool 层     tools/ (自注册插件系统 + 分类)
│  ├─ ToolSet  toolspec.py (多厂商 schema 转换)
│  └─ 8 tools   execute_bash / fs_read / fs_write / memory / todo / web_search / clarify / timestamp
└─ Core 层     config / compressor / theme / memory / tips
```

## Key Features

- **Pipeline Stage 洋葱模型**: 消息处理管道化，每个 Stage 可前后置拦截（借鉴 AstrBot）
- **自注册工具系统**: tools/ 下每 .py 文件导出 TOOL_SCHEMA + tool_run 自动注册
- **工具分类**: 每个工具标注 category（system/filesystem/execution/memory/communication/utility）
- **ToolSet 多厂商适配**: 一套工具定义生成 OpenAI / Anthropic / Google 三种 schema
- **Reflection Loop**: 工具出错时自动反思重试（最多2轮，借鉴 RDT 循环深度）
- **三级记忆**: L1 工作记忆 / L2 长期记忆(`/memory`) / L3 项目记忆(KILEE.md)
- **Agent Hooks**: on_llm_request / on_llm_response / on_tool_call / on_tool_result
- **自动压缩**: 上下文 >6000 tokens 自动触发压缩
- **DuckDuckGo 搜索**: 无需 API Key

## Conventions

- Reply in Chinese
- Use markdown code blocks for code
- Always use tools directly instead of describing actions

## 自注册工具规范

在 `kilee/tools/` 下创建 .py 文件:

```python
from kilee.tools import ToolCategory

TOOL_CATEGORY = ToolCategory.UTILITY
TOOL_METADATA = {"local": True}

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "tool_name",
        "description": "...",
        "parameters": {...}
    }
}

def tool_run(**kwargs) -> str:
    ...
```
