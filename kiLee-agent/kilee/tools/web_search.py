"""Web 搜索工具 — 使用 DuckDuckGo（无需 API Key，借鉴 hermes-agent web_tools）"""
from kilee.tools import ToolCategory

TOOL_CATEGORY = ToolCategory.COMMUNICATION
TOOL_METADATA = {"external_api": True, "no_key_required": True}


import json
import urllib.request
import urllib.parse
import re

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "搜索互联网获取最新信息。当需要实时数据、新闻、文档或不确定的知识时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回结果数量，默认5", "default": 5},
            },
            "required": ["query"],
        },
    },
}


def tool_run(query: str, limit: int = 5) -> str:
    try:
        # DuckDuckGo Instant Answer API
        params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
        url = f"https://api.duckduckgo.com/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "kiLee-agent/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        results = []

        # Abstract (直接答案)
        if data.get("AbstractText"):
            results.append(f"[摘要] {data['AbstractText']}\n来源: {data.get('AbstractURL', '')}")

        # RelatedTopics
        for topic in data.get("RelatedTopics", [])[:limit]:
            if isinstance(topic, dict) and topic.get("Text"):
                text = topic["Text"][:200]
                url_link = topic.get("FirstURL", "")
                results.append(f"• {text}\n  {url_link}")
            if len(results) >= limit:
                break

        if not results:
            # fallback: HTML 搜索抓取摘要
            return _ddg_html_search(query, limit)

        return "\n\n".join(results[:limit])

    except Exception as e:
        return f"[ERROR] 搜索失败: {e}"
run = tool_run


def _ddg_html_search(query: str, limit: int) -> str:
    """Fallback: 抓取 DuckDuckGo HTML 结果"""
    try:
        params = urllib.parse.urlencode({"q": query, "kl": "cn-zh"})
        url = f"https://html.duckduckgo.com/html/?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # 提取结果片段
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        titles   = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
        urls     = re.findall(r'class="result__url"[^>]*>(.*?)</span>', html, re.DOTALL)

        def clean(s): return re.sub(r'<[^>]+>', '', s).strip()

        results = []
        for i in range(min(limit, len(titles))):
            title   = clean(titles[i]) if i < len(titles) else ""
            snippet = clean(snippets[i]) if i < len(snippets) else ""
            link    = clean(urls[i]) if i < len(urls) else ""
            if title or snippet:
                results.append(f"• {title}\n  {snippet}\n  {link}")

        return "\n\n".join(results) if results else "(无搜索结果)"
    except Exception as e:
        return f"[ERROR] {e}"
