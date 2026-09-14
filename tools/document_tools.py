"""Document-generation tools. Unlike the other tools/*.py modules, these are
built by a factory (build_tools) that closes over a `send_document`
callback injected by the caller (the Telegram layer, in production; a
local file-path printer in the terminal REPL) -- so a generated PDF/PPTX is
pushed to the chat directly as a side effect of the tool call, with no
separate 'pending attachment' queue for the rest of the system to manage."""

from typing import Awaitable, Callable

from agent.tool_registry import ToolSpec
from documents import analysis_deck, invoice_pdf
from domain import analytics, billing, inventory, preferences
from domain.khata import resolve_customer
from tools._common import call_domain

SendDocument = Callable[[int, str, str], Awaitable[None]]  # (chat_id, file_path, caption) -> None


def build_tools(send_document: SendDocument) -> list[ToolSpec]:
    async def _generate_invoice_pdf(conn, chat_id, tool_call_id, *, bill_id):
        bill = billing.get_bill(conn, bill_id)
        if bill["status"] != "finalized":
            return {"status": "rejected", "message": "Only a finalized bill can be turned into an invoice -- finalize it first."}

        summary = billing.get_bill_summary(conn, bill_id)
        for line in summary["lines"]:
            line["hsn_code"] = inventory.get_product(conn, line["product_id"])["hsn_code"]

        shop = preferences.get_preferences(conn)
        customer_name = resolve_customer(conn, bill["customer_id"])["name"] if bill.get("customer_id") else None

        path = invoice_pdf.render_invoice_pdf(summary, shop, customer_name)
        await send_document(chat_id, path, f"Tax invoice for Bill #{bill_id}")
        return {"status": "ok", "message": f"Invoice PDF for bill #{bill_id} sent to this chat."}

    async def _generate_analysis_deck(conn, chat_id, tool_call_id, *, start_date, end_date):
        summary = call_domain(lambda: analytics.get_sales_range_summary(conn, start_date, end_date))
        if summary["status"] != "ok":
            return summary
        reorder_suggestions = inventory.get_reorder_suggestions(conn)
        shop_name = preferences.get_preferences(conn)["shop_name"]

        path = analysis_deck.render_analysis_deck(shop_name, start_date, end_date, summary, reorder_suggestions)
        await send_document(chat_id, path, f"Sales analysis: {start_date} to {end_date}")
        return {"status": "ok", "message": f"Analysis deck for {start_date} to {end_date} sent to this chat."}

    return [
        ToolSpec(
            name="generate_invoice_pdf",
            description="Generate and send a clean, GST-correct PDF tax invoice for a finalized bill. Only works on a finalized bill (not a draft).",
            parameters={"type": "object", "properties": {"bill_id": {"type": "integer"}}, "required": ["bill_id"]},
            handler=_generate_invoice_pdf,
        ),
        ToolSpec(
            name="generate_analysis_deck",
            description=(
                "Generate and send a PowerPoint sales-analysis deck for a date range: totals, tax "
                "collected, top items, daily trend, payment-mode split, and stock/reorder health, "
                "with real charts and computed insights. Use YYYY-MM-DD dates; for 'this week' figure "
                "out the actual date range yourself before calling."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["start_date", "end_date"],
            },
            handler=_generate_analysis_deck,
        ),
    ]
