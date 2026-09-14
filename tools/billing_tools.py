from agent.tool_registry import ToolSpec
from domain import billing
from tools._common import call_domain

_PRODUCT_REF_DESC = "Product id (if known) or free text name, e.g. 'maggi' or '2 kg sugar'."
_LINE_REF_DESC = "The bill line to edit: its numeric line id, or the product name/text used when it was added, e.g. 'butter'."


async def _get_open_bill(conn, chat_id, tool_call_id):
    result = billing.get_open_bill(conn, chat_id)
    if result is None:
        return {"status": "not_found", "message": "No draft bill is open right now."}
    return {"status": "ok", **result}


async def _start_bill(conn, chat_id, tool_call_id, *, customer_ref=None):
    return call_domain(lambda: billing.start_bill(conn, chat_id, customer_ref=customer_ref))


async def _add_bill_item(conn, chat_id, tool_call_id, *, bill_id, product_ref, qty, unit=None):
    return call_domain(lambda: billing.add_bill_item(conn, bill_id, product_ref, qty, unit))


async def _update_bill_item_qty(conn, chat_id, tool_call_id, *, bill_id, line_ref, new_qty):
    return call_domain(lambda: billing.update_bill_item_qty(conn, bill_id, line_ref, new_qty))


async def _remove_bill_item(conn, chat_id, tool_call_id, *, bill_id, line_ref):
    return call_domain(lambda: billing.remove_bill_item(conn, bill_id, line_ref))


async def _set_bill_payment(conn, chat_id, tool_call_id, *, bill_id, mode, reference=None):
    return call_domain(lambda: billing.set_bill_payment(conn, bill_id, mode, reference))


async def _get_bill_summary(conn, chat_id, tool_call_id, *, bill_id):
    return call_domain(lambda: billing.get_bill_summary(conn, bill_id))


async def _finalize_bill(conn, chat_id, tool_call_id, *, bill_id, allow_below_cost=False):
    idem_key = f"{chat_id}:{tool_call_id}"
    return call_domain(lambda: billing.finalize_bill(
        conn, bill_id, idempotency_key=idem_key, allow_below_cost=allow_below_cost
    ))


async def _cancel_bill(conn, chat_id, tool_call_id, *, bill_id):
    return call_domain(lambda: billing.cancel_bill(conn, bill_id))


TOOLS = [
    ToolSpec(
        name="get_open_bill",
        description="Get the draft bill currently being built in this chat, if any. Call this if you're unsure whether a bill is already in progress.",
        parameters={"type": "object", "properties": {}},
        handler=_get_open_bill,
    ),
    ToolSpec(
        name="start_bill",
        description="Start a new draft bill for this chat. If a draft is already open, returns that same draft instead of creating a second one. Only attach customer_ref if the owner names a customer (needed for a credit/khata sale).",
        parameters={
            "type": "object",
            "properties": {"customer_ref": {"type": "string", "description": "Customer name, if this bill is for a known khata customer."}},
        },
        handler=_start_bill,
    ),
    ToolSpec(
        name="add_bill_item",
        description="Add one line item to a draft bill. Price and GST are looked up from the catalog automatically -- never state them yourself.",
        parameters={
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "product_ref": {"type": "string", "description": _PRODUCT_REF_DESC},
                "qty": {"type": "number"},
                "unit": {"type": "string", "description": "Only if the owner's unit differs from the product's stored unit."},
            },
            "required": ["bill_id", "product_ref", "qty"],
        },
        handler=_add_bill_item,
    ),
    ToolSpec(
        name="update_bill_item_qty",
        description="Change the quantity of an existing line on a draft bill (e.g. 'make it 6 Maggi').",
        parameters={
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "line_ref": {"type": "string", "description": _LINE_REF_DESC},
                "new_qty": {"type": "number"},
            },
            "required": ["bill_id", "line_ref", "new_qty"],
        },
        handler=_update_bill_item_qty,
    ),
    ToolSpec(
        name="remove_bill_item",
        description="Drop a line from a draft bill entirely (e.g. 'drop the butter').",
        parameters={
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "line_ref": {"type": "string", "description": _LINE_REF_DESC},
            },
            "required": ["bill_id", "line_ref"],
        },
        handler=_remove_bill_item,
    ),
    ToolSpec(
        name="set_bill_payment",
        description="Set (or change) how a draft bill will be paid. mode='credit' requires the bill to already have a customer attached (pass customer_ref to start_bill first).",
        parameters={
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "mode": {"type": "string", "enum": ["cash", "upi", "card", "credit"]},
                "reference": {"type": "string", "description": "UPI/card transaction reference, if the owner gives one."},
            },
            "required": ["bill_id", "mode"],
        },
        handler=_set_bill_payment,
    ),
    ToolSpec(
        name="get_bill_summary",
        description="Get the current lines and running tax/total breakup of a draft or finalized bill -- use this to answer 'what's the bill so far'.",
        parameters={"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
        handler=_get_bill_summary,
    ),
    ToolSpec(
        name="finalize_bill",
        description=(
            "Commit a draft bill: decrements stock, computes the final GST breakup, and "
            "(for credit sales) charges the customer's khata. This is the only tool that "
            "actually affects stock for a sale -- everything before this is just editing a "
            "draft. Requires a payment mode to already be set. If it's refused for being "
            "priced below cost, ask the owner to confirm, then call again with "
            "allow_below_cost=true only if they say yes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "bill_id": {"type": "integer"},
                "allow_below_cost": {"type": "boolean", "description": "Only set true after the owner explicitly confirms a below-cost sale."},
            },
            "required": ["bill_id"],
        },
        handler=_finalize_bill,
    ),
    ToolSpec(
        name="cancel_bill",
        description="Abandon a draft bill without any effect on stock (nothing was ever decremented).",
        parameters={"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
        handler=_cancel_bill,
    ),
]
