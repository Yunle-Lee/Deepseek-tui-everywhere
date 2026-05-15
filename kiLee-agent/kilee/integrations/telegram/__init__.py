"""
DeepSeek Telegram Bridge (Python-native)

Telegram bot bridge that directly invokes kiLee Agent core.
Compatible with the upstream Node.js bridge command set.

Usage:
    kilee telegram                    # start from CLI
    python -m kilee.integrations.telegram  # or as module
"""

from .bot import run_bot

__all__ = ["run_bot"]
