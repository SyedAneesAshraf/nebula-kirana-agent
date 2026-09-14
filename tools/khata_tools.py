from agent.tool_registry import ToolSpec
from domain import khata
from tools._common import call_domain

_CUSTOMER_REF_DESC = "Customer id (if known) or their name, e.g. 'Ramesh'."


def _find_customer(conn, chat_id, tool_call_id, *, name):
    return call_domain(lambda: khata.find_customer(conn, name))


def _add_customer(conn, chat_id, tool_call_id, *, name, phone=None, aliases=""):
    return call_domain(lambda: khata.add_customer(conn, name, phone, aliases))


def _get_khata_balance(conn, chat_id, tool_call_id, *, customer_ref):
    return call_domain(lambda: khata.get_khata_balance(conn, customer_ref))


def _list_khata_customers(conn, chat_id, tool_call_id, *, min_balance=0):
    return call_domain(lambda: khata.list_khata_customers(conn, min_balance))


def _charge_to_credit(conn, chat_id, tool_call_id, *, customer_ref, amount):
    idem_key = f"{chat_id}:{tool_call_id}"
    return call_domain(lambda: khata.charge_to_credit(
        conn, customer_ref=customer_ref, amount=amount, idempotency_key=idem_key
    ))


def _record_khata_payment(conn, chat_id, tool_call_id, *, customer_ref, amount, mode, reference=None):
    idem_key = f"{chat_id}:{tool_call_id}"
    return call_domain(lambda: khata.record_khata_payment(
        conn, customer_ref=customer_ref, amount=amount, mode=mode, reference=reference,
        idempotency_key=idem_key,
    ))


TOOLS = [
    ToolSpec(
        name="find_customer",
        description="Look up a khata customer by name. Returns a single confident match, candidates to disambiguate, or not-found -- a not-found result means you should ask the owner whether to add them as a new customer, never assume.",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        handler=_find_customer,
    ),
    ToolSpec(
        name="add_customer",
        description="Register a new khata customer. Only call this after the owner confirms they want to add someone who wasn't found by find_customer.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "aliases": {"type": "string", "description": "Comma-separated alternate names/spellings."},
            },
            "required": ["name"],
        },
        handler=_add_customer,
    ),
    ToolSpec(
        name="get_khata_balance",
        description="Get a customer's current outstanding balance (how much they owe the shop).",
        parameters={"type": "object", "properties": {"customer_ref": {"type": "string", "description": _CUSTOMER_REF_DESC}}, "required": ["customer_ref"]},
        handler=_get_khata_balance,
    ),
    ToolSpec(
        name="list_khata_customers",
        description="List customers with an outstanding balance above min_balance (default 0) -- for 'who owes money' style questions.",
        parameters={"type": "object", "properties": {"min_balance": {"type": "number"}}},
        handler=_list_khata_customers,
    ),
    ToolSpec(
        name="charge_to_credit",
        description="Add a standalone amount to a customer's khata balance directly (not tied to a bill), e.g. 'put ₹500 on Ramesh's credit'. Refuses if the customer doesn't exist.",
        parameters={
            "type": "object",
            "properties": {"customer_ref": {"type": "string", "description": _CUSTOMER_REF_DESC}, "amount": {"type": "number"}},
            "required": ["customer_ref", "amount"],
        },
        handler=_charge_to_credit,
    ),
    ToolSpec(
        name="record_khata_payment",
        description="Record a customer paying down their khata balance, e.g. 'Ramesh paid ₹300'. Refuses if the customer doesn't exist. If the payment exceeds their balance it still applies, but the result flags the resulting credit -- tell the owner.",
        parameters={
            "type": "object",
            "properties": {
                "customer_ref": {"type": "string", "description": _CUSTOMER_REF_DESC},
                "amount": {"type": "number"},
                "mode": {"type": "string", "enum": ["cash", "upi", "card"]},
                "reference": {"type": "string"},
            },
            "required": ["customer_ref", "amount", "mode"],
        },
        handler=_record_khata_payment,
    ),
]
