"""Tips shown at startup to help users discover features."""
import random

TIPS = [
    "/compact  compress context to save tokens",
    "/memory   view persistent cross-session memory",
    "/memory clear  wipe all saved memory",
    "/model deepseek-reasoner  switch to reasoning model",
    "/clear  reset conversation history",
    "Share project info — KiLee will remember it",
    "Paste code directly for KiLee to analyze",
    "Context auto-compresses when it gets long",
    "Ctrl+C interrupts the current task",
    "/tips  show more usage tips",
    "KiLee picks the right tool automatically",
    "/model  check or switch the current model",
]

def get_random_tip() -> str:
    return random.choice(TIPS)
