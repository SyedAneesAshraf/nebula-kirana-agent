from agent.tool_registry import ToolSpec
from domain import preferences
from tools._common import call_domain


async def _get_preferences(conn, chat_id, tool_call_id):
    return call_domain(lambda: preferences.get_preferences(conn))


async def _set_preference(conn, chat_id, tool_call_id, *, key, value):
    return call_domain(lambda: preferences.set_preference(conn, key, value))


TOOLS = [
    ToolSpec(
        name="get_preferences",
        description="Get the shop's standing preferences (default payment mode, default brands, shop name/GSTIN/address for invoices, invoice footer). These already appear in your system prompt at the start of every chat, so you don't normally need to call this -- use it if you want to double-check a value mid-conversation.",
        parameters={"type": "object", "properties": {}},
        handler=_get_preferences,
    ),
    ToolSpec(
        name="set_preference",
        description="Update a standing shop preference so it's remembered in future chats, including after /new. Only accepts known keys: shop_name, shop_gstin, shop_address, invoice_footer, default_payment_mode, default_atta, default_rice, default_dal.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": [
                        "shop_name", "shop_gstin", "shop_address", "invoice_footer",
                        "default_payment_mode", "default_atta", "default_rice", "default_dal",
                    ],
                },
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
        handler=_set_preference,
    ),
]
