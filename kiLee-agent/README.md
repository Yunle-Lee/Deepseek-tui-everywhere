<div align="center">

```
  ██╗  ██╗██╗██╗     ███████╗███████╗
  ██║ ██╔╝██║██║     ██╔════╝██╔════╝
  █████╔╝ ██║██║     █████╗  █████╗
  ██╔═██╗ ██║██║     ██╔══╝  ██╔══╝
  ██║  ██╗██║███████╗███████╗███████╗
  ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝
        ◈ A G E N T  v0.1 ◈
```

**A DeepSeek-powered terminal AI Agent**

read files · run commands · write code · remember context

![Python](https://img.shields.io/badge/Python-3.10+-00CFCF?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-00AFAF?style=flat-square)
![Model](https://img.shields.io/badge/Model-DeepSeek-007F7F?style=flat-square)

</div>

---

## 简介

KiLee 是一个运行在终端里的 AI Agent，由 DeepSeek 驱动。它可以直接操作你的文件系统、执行 shell 命令、编写和调试代码，并通过持久化记忆跨会话记住你的偏好和项目信息。

## 快速开始

**安装**

```bash
git clone https://github.com/your-username/kilee-agent.git
cd kilee-agent
pip install -e .
```

**启动**

```bash
kilee
```

首次启动会自动弹出配置向导，引导你完成 API Key 和模型的设置。

**或手动配置**

```bash
kilee setup
```

## 配置向导

启动向导分三步：

1. **选择 AI Provider** — DeepSeek / OpenAI / Groq / OpenRouter / 自定义
2. **输入 API Key** — 隐藏输入，保存到 `~/.kilee/config.json`
3. **选择默认模型** — 根据 provider 列出可用模型

| Provider | Base URL | 推荐模型 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` / `deepseek-reasoner` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenRouter | `https://openrouter.ai/api/v1` | 任意模型 |
| 自定义 | 你的 URL | 任意 OpenAI 兼容模型 |

## 功能

### 内置工具

| 工具 | 说明 |
|---|---|
| `execute_bash` | 执行 shell 命令，内置危险命令拦截 |
| `fs_read` | 读文件 / 列目录 / 正则搜索 |
| `fs_write` | 创建 / 编辑 / 追加文件，支持 diff 预览 |
| `save_memory` | 持久化记忆，跨会话可用 |

### 项目上下文（Context Engineering）

在项目根目录创建 `KILEE.md`，KiLee 启动时自动加载为静态上下文：

```markdown
# My Project

## Stack
- Python 3.11, FastAPI, PostgreSQL

## Conventions
- 使用类型注解
- 测试用 pytest
```

同样支持 `CLAUDE.md` 和 `AGENTS.md`。

### 上下文压缩

对话超过 6000 tokens 时自动压缩，保留头尾、摘要中间内容。也可手动触发：

```
/compact
```

### 持久化记忆

KiLee 会主动记住你提到的重要信息（项目偏好、技术栈等），存储在 `~/.kilee/memory.json`，下次启动自动加载。

## Slash 命令

| 命令 | 说明 |
|---|---|
| `/help` | 查看所有命令 |
| `/clear` | 清空对话历史 |
| `/compact` | 手动压缩上下文 |
| `/memory` | 查看持久记忆 |
| `/memory clear` | 清除所有记忆 |
| `/model [name]` | 查看 / 切换模型 |
| `/tips` | 随机显示使用技巧 |
| `/exit` | 退出 |

## CLI 命令

```bash
kilee           # 启动对话（首次自动 setup）
kilee setup     # 重新运行配置向导
kilee login     # 仅更新 API Key
kilee whoami    # 查看当前配置
kilee doctor    # 检查依赖环境
kilee settings  # 查看完整配置
kilee translate <描述>  # 自然语言转 shell 命令
```

## 项目结构

```
kilee-agent/
├── README.md
├── KILEE.md          # 项目上下文示例
├── pyproject.toml
└── kilee/
    ├── main.py       # CLI 入口 & 对话循环
    ├── agent.py      # Agent 主循环 & 工具调用
    ├── setup.py      # 首次配置向导
    ├── config.py     # 配置管理
    ├── compressor.py # 上下文压缩
    ├── theme.py      # 视觉主题
    ├── tips.py       # 使用技巧
    └── tools/
        ├── execute_bash.py
        ├── fs_read.py
        ├── fs_write.py
        └── memory.py
```

## 依赖

```
Python >= 3.10
openai >= 1.0.0
rich >= 13.0.0
click >= 8.0.0
prompt-toolkit >= 3.0.0
```

## License

MIT © [kilee.cn](https://kilee.cn)
