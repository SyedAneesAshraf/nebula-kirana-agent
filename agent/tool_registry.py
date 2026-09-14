"""Flat tool registry. Every tools/*.py module exports a TOOLS list of
ToolSpec objects; this module merges them into the single list sent on every
model request and dispatches an incoming tool call back to its handler.

Handler signature is always async (conn, chat_id, tool_call_id, **model_args):
chat_id is bound by the dispatcher from the authenticated Telegram update --
never a model-supplied argument, and defensively stripped if a model ever
tries -- and tool_call_id lets a handler derive a stable idempotency key
without asking the model to invent one itself. Handlers are async (even the
ones that never await anything) so a document tool can directly `await` a
Telegram send as a side effect of the tool call, with no separate
'pending attachment' queue for the caller to manage."""

import json
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema: {"type": "object", "properties": {...}, "required": [...]}
    handler: Callable[..., Awaitable[dict]]


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]):
        self._by_name: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._by_name:
                raise ValueError(f"Duplicate tool name: {spec.name}")
            self._by_name[spec.name] = spec

    def specs(self) -> list[ToolSpec]:
        return list(self._by_name.values())

    async def dispatch(self, conn, chat_id: int, tool_call_id: str, name: str, arguments: dict) -> dict:
        spec = self._by_name.get(name)
        if spec is None:
            result = {"status": "error", "message": f"Unknown tool '{name}'."}
            self._audit(conn, chat_id, name, arguments, result)
            return result
        arguments = dict(arguments or {})
        arguments.pop("chat_id", None)  # never trust a model-supplied identity/tenant field
        arguments.pop("idempotency_key", None)  # idempotency is derived server-side, not model-supplied
        try:
            result = await spec.handler(conn, chat_id, tool_call_id, **arguments)
        except TypeError as e:
            result = {"status": "error", "message": f"Bad arguments for '{name}': {e}"}
        self._audit(conn, chat_id, name, arguments, result)
        return result

    @staticmethod
    def _audit(conn, chat_id: int, name: str, arguments: dict, result: dict) -> None:
        """Traceability layer, independent of the domain guards that actually
        enforce business rules -- every tool call and its outcome is logged
        regardless of which path (success/refusal/error) it took."""
        conn.execute(
            "INSERT INTO audit_log (chat_id, tool_name, tool_input_json, decision) VALUES (?, ?, ?, ?)",
            (chat_id, name, json.dumps(arguments, default=str), result.get("status", "unknown")),
        )
