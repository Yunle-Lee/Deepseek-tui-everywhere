"""
DeepSeek Feishu / Lark Bridge (Python-native)

Feishu/Lark bot bridge that directly invokes kiLee Agent core.
Uses the official Lark Open API Python SDK with WebSocket long-connection.

Usage:
    kilee feishu                     # start from CLI
    python -m kilee.integrations.feishu  # or as module
"""

from .bot import run_bot

__all__ = ["run_bot"]
