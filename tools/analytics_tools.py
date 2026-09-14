from agent.tool_registry import ToolSpec
from domain import analytics
from tools._common import call_domain


async def _get_daily_summary(conn, chat_id, tool_call_id, *, date=None):
    return call_domain(lambda: analytics.get_daily_summary(conn, date))


async def _close_day(conn, chat_id, tool_call_id, *, date=None):
    return call_domain(lambda: analytics.close_day(conn, date))


async def _get_sales_range_summary(conn, chat_id, tool_call_id, *, start_date, end_date):
    return call_domain(lambda: analytics.get_sales_range_summary(conn, start_date, end_date))


TOOLS = [
    ToolSpec(
        name="get_daily_summary",
        description="Get today's (or a given date's) sales total, tax collected, cash/UPI/card/credit split, and top items -- for 'today's sales?' style questions.",
        parameters={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; omit for today."}}},
        handler=_get_daily_summary,
    ),
    ToolSpec(
        name="close_day",
        description="Close out a day (default today), returning its final summary. Use when the owner says 'close the day'.",
        parameters={"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; omit for today."}}},
        handler=_close_day,
    ),
    ToolSpec(
        name="get_sales_range_summary",
        description="Get sales totals, tax collected, payment-mode split, daily trend, and top items over a date range -- use this to gather the data for an analysis deck.",
        parameters={
            "type": "object",
            "properties": {"start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["start_date", "end_date"],
        },
        handler=_get_sales_range_summary,
    ),
]
