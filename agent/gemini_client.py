"""The tool-calling control loop against Gemini: send contents+tools+system
instruction, execute any function_calls against our registry, feed results
back as a 'user'-role Content carrying function_response parts, repeat until
the model replies with plain text. This is the brief's 'observe -> reason ->
act (call tool) -> feed result back -> continue' loop, written explicitly
rather than supplied by a harness.

Gemini's message shape differs from OpenAI/Mistral-style APIs in three ways
that shaped this file and the agent_messages schema: there is no separate
system-role message (system_instruction is its own config field, rebuilt
fresh every call so a preference change or /new is picked up immediately);
there is no separate tool/function role (a function result is a 'user'-role
Content whose parts are function_response objects); and a single Content's
parts list is where multiple tool calls in one model turn actually live."""

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config
from agent.tool_registry import ToolRegistry

MAX_TOOL_ROUNDS = 8

_FALLBACK_REPLY = (
    "Sorry, that took too many steps to work through -- please try rephrasing "
    "or breaking it into smaller requests."
)


def _part_to_dict(part: types.Part) -> dict:
    return part.model_dump(exclude_none=True, mode="json")


def _is_quota_exhausted(e: Exception) -> bool:
    return isinstance(e, genai_errors.ClientError) and "RESOURCE_EXHAUSTED" in str(e)


class GeminiAgent:
    def __init__(self, registry: ToolRegistry):
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._registry = registry
        self._tool = types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters_json_schema=spec.parameters,
            )
            for spec in registry.specs()
        ])
        # Preferred model first, then the configured fallbacks (deduped, order preserved).
        self._models = list(dict.fromkeys([config.GEMINI_MODEL, *config.GEMINI_MODEL_FALLBACKS]))
        self._model_index = 0  # sticky across turns: once one works, keep using it

    async def _generate(self, contents, gen_config):
        """Try the current model; on quota exhaustion, advance to the next
        model in the fallback list and retry, so one model running dry
        doesn't stop the bot mid-conversation."""
        last_error = None
        for _ in range(len(self._models)):
            model = self._models[self._model_index]
            try:
                return await self._client.aio.models.generate_content(
                    model=model, contents=contents, config=gen_config,
                )
            except genai_errors.ClientError as e:
                if not _is_quota_exhausted(e):
                    raise
                last_error = e
                self._model_index = (self._model_index + 1) % len(self._models)
        raise last_error

    async def run_turn(
        self, conn, chat_id: int, system_prompt: str, history: list[dict], user_text: str
    ) -> tuple[str, list[dict]]:
        """`history` is the prior turns as plain {"role": "user"|"model", "parts":
        [...]} dicts (JSON-safe, matching what's persisted). Returns
        (final_assistant_text, new_entries) where new_entries is every Content
        produced by this turn -- the user's message plus every model/
        function-result exchange that followed -- for the caller to persist."""
        user_entry = {"role": "user", "parts": [{"text": user_text}]}
        contents: list[dict] = [*history, user_entry]
        new_entries: list[dict] = [user_entry]

        gen_config = types.GenerateContentConfig(system_instruction=system_prompt, tools=[self._tool])

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._generate(contents, gen_config)
            model_content = response.candidates[0].content
            model_parts = [_part_to_dict(p) for p in (model_content.parts or [])]
            model_entry = {"role": "model", "parts": model_parts}
            contents.append(model_entry)
            new_entries.append(model_entry)

            calls = response.function_calls or []
            if not calls:
                return response.text or "", new_entries

            response_parts = []
            for i, call in enumerate(calls):
                call_id = call.id or f"{chat_id}:{len(new_entries)}:{i}"
                result = await self._registry.dispatch(conn, chat_id, call_id, call.name, call.args or {})
                fr = {"name": call.name, "response": {"output": result}}
                if call.id:
                    fr["id"] = call.id
                response_parts.append({"function_response": fr})

            result_entry = {"role": "user", "parts": response_parts}
            contents.append(result_entry)
            new_entries.append(result_entry)

        return _FALLBACK_REPLY, new_entries
