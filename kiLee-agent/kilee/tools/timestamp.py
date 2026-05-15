"""获取当前时间和日期（演示 @register_tool 装饰器）"""
from kilee.tools import register_tool, ToolCategory


@register_tool(
    name="get_timestamp",
    description="获取当前日期和时间信息。当你需要知道当前时间时使用。",
    category=ToolCategory.UTILITY,
    metadata={"local": True},
)
def tool_run(format: str = "full") -> str:
    """
    获取当前时间。
    format: 输出格式 - full=完整日期时间, date=仅日期, time=仅时间, iso=ISO格式
    """
    from datetime import datetime
    now = datetime.now()
    if format == "date":
        return now.strftime("%Y-%m-%d")
    elif format == "time":
        return now.strftime("%H:%M:%S")
    elif format == "iso":
        return now.isoformat()
    else:
        return now.strftime("%Y-%m-%d %H:%M:%S")
