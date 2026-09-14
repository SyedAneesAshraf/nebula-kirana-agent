from agent.tool_registry import ToolSpec
from domain import inventory
from tools._common import call_domain

_PRODUCT_REF_DESC = (
    "The product to act on: either its numeric id (if already known from an "
    "earlier tool result in this conversation) or free text like 'maggi' or "
    "'aashirvaad atta'."
)


async def _find_product(conn, chat_id, tool_call_id, *, query):
    return call_domain(lambda: inventory.find_product(conn, query))


async def _get_product(conn, chat_id, tool_call_id, *, product_id):
    return call_domain(lambda: inventory.get_product(conn, product_id))


async def _add_product(conn, chat_id, tool_call_id, *, name, unit, is_loose, hsn_code, gst_rate,
                  cost_price, mrp, reorder_level=0, opening_qty=0, aliases=""):
    return call_domain(lambda: inventory.add_product(
        conn, name=name, unit=unit, is_loose=is_loose, hsn_code=hsn_code, gst_rate=gst_rate,
        cost_price=cost_price, mrp=mrp, reorder_level=reorder_level,
        opening_qty=opening_qty, aliases=aliases,
    ))


async def _receive_stock(conn, chat_id, tool_call_id, *, product_ref, qty, cost_price=None, mrp=None):
    idem_key = f"{chat_id}:{tool_call_id}"
    return call_domain(lambda: inventory.receive_stock(
        conn, product_ref=product_ref, qty=qty, cost_price=cost_price, mrp=mrp,
        idempotency_key=idem_key,
    ))


async def _adjust_stock(conn, chat_id, tool_call_id, *, product_id, delta, reason):
    return call_domain(lambda: inventory.adjust_stock(conn, product_id=product_id, delta=delta, reason=reason))


async def _list_low_stock(conn, chat_id, tool_call_id):
    return call_domain(lambda: inventory.list_low_stock(conn))


async def _get_reorder_suggestions(conn, chat_id, tool_call_id):
    return call_domain(lambda: inventory.get_reorder_suggestions(conn))


TOOLS = [
    ToolSpec(
        name="find_product",
        description=(
            "Look up a product by name before adding it to a bill or checking stock. "
            "Returns a single confident match, a list of candidates to disambiguate, "
            "or not-found -- never guesses on your behalf."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Product name or partial name, e.g. 'maggi' or 'atta'."},
            },
            "required": ["query"],
        },
        handler=_find_product,
    ),
    ToolSpec(
        name="get_product",
        description="Get full details (price, stock, GST, HSN) of a product by its numeric id.",
        parameters={
            "type": "object",
            "properties": {"product_id": {"type": "integer"}},
            "required": ["product_id"],
        },
        handler=_get_product,
    ),
    ToolSpec(
        name="add_product",
        description=(
            "Register a brand-new SKU in the catalog. Refuses if the name+unit already "
            "exists, or if gst_rate is not one of the store's allowed slabs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "unit": {"type": "string", "description": "kg | g | litre | ml | packet | dozen | piece"},
                "is_loose": {"type": "boolean"},
                "hsn_code": {"type": "string"},
                "gst_rate": {"type": "number", "enum": [0, 3, 5, 18, 40]},
                "cost_price": {"type": "number"},
                "mrp": {"type": "number", "description": "Tax-inclusive selling price."},
                "reorder_level": {"type": "number"},
                "opening_qty": {"type": "number"},
                "aliases": {"type": "string", "description": "Comma-separated alternate names for lookup."},
            },
            "required": ["name", "unit", "is_loose", "hsn_code", "gst_rate", "cost_price", "mrp"],
        },
        handler=_add_product,
    ),
    ToolSpec(
        name="receive_stock",
        description=(
            "Record newly received stock for an existing product, increasing quantity on "
            "hand. Optionally update cost price / MRP if the owner mentions new ones."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_ref": {"type": "string", "description": _PRODUCT_REF_DESC},
                "qty": {"type": "number"},
                "cost_price": {"type": "number"},
                "mrp": {"type": "number"},
            },
            "required": ["product_ref", "qty"],
        },
        handler=_receive_stock,
    ),
    ToolSpec(
        name="adjust_stock",
        description=(
            "Manually correct stock for breakage, expiry, or a count error, by a signed "
            "delta. A reason is mandatory. Cannot take stock negative."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "delta": {"type": "number", "description": "Positive to add stock back, negative to remove."},
                "reason": {"type": "string"},
            },
            "required": ["product_id", "delta", "reason"],
        },
        handler=_adjust_stock,
    ),
    ToolSpec(
        name="list_low_stock",
        description="List every product at or below its reorder level right now.",
        parameters={"type": "object", "properties": {}},
        handler=_list_low_stock,
    ),
    ToolSpec(
        name="get_reorder_suggestions",
        description=(
            "List products worth reordering soon: combines a reorder-level breach with "
            "recent sales velocity to estimate days of stock left."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_get_reorder_suggestions,
    ),
]
