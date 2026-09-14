# Kirana Ops Agent

A conversational agent that runs a small Indian kirana (neighbourhood grocery) store
end-to-end from a Telegram chat — receiving stock, cutting GST-correct bills, tracking
customer credit (khata), summarising the day's sales, and generating invoices and
analysis decks — driven entirely by natural language. There is no command menu, no
web dashboard, and no keyword/regex router: a model reasons over a set of purpose-built
tools and decides what to call.

## What it can do

- **Receive stock** — "50 packets of Maggi came in, cost 12, MRP 14"
- **Add a new product** — "new item: Amul Butter 100g, GST 5%, MRP 62"
- **Cut a bill, over several messages, with edits mid-build** — "make a bill: 2kg sugar,
  1 aashirvaad atta, 4 maggi, UPI" → "actually drop the maggi, make it 6 instead"
- **Stock and reorder queries** — "how much sugar is left?", "what's running out?"
- **Customer credit (khata)** — "put ₹500 on Ramesh's credit", "Ramesh paid ₹300",
  "what's Ramesh's balance?"
- **Daily close** — "today's sales?" → total, tax collected, cash/UPI/card/credit split,
  top items
- **GST invoice as a PDF** — "send me that bill as a PDF"
- **Sales analysis as a PowerPoint** — "make this week's sales analysis deck" → real
  charts, not screenshots
- **Standing preferences that persist across conversations** — "always assume UPI
  unless I say cash" — remembered even after the conversation history is cleared

When a request is genuinely ambiguous (e.g. "atta" could mean loose atta or a specific
5kg branded packet), the agent asks a clarifying question instead of guessing — that
decision comes from the model reading structured tool output, not from a hardcoded
branch.

## Architecture

**Harness:** a small, hand-rolled tool-calling loop against Google's Gemini API
(`google-genai`), intentionally not built on any agent framework. The loop is the
textbook shape: send the conversation + a flat list of tool declarations → if the
model returns one or more function calls, execute them against the store and feed the
results back → repeat until it replies with plain text. Nothing about the business
logic depends on this being Gemini specifically; the tool surface is provider-agnostic
by design (JSON-schema function declarations + plain dict results), so swapping the
underlying model is a change to one file.

**No LangGraph-style state machine, no per-intent routing graph.** There is exactly one
agent reasoning freely over a flat, well-named tool surface — not a node per command.

**No subagents.** This domain is a single continuously-running conversation about one
shop's books (a bill being built, a khata balance being checked); splitting it across
subagents would fragment shared context for no benefit. Document generation, the one
task that might look subagent-shaped, is fully self-contained per call (build a file,
confirm) and is just a tool.

**Business rules live in the tool/data layer, not the prompt.** A `domain/` package
holds 100% of the actual logic — GST computation, stock mutation, bill lifecycle, khata
ledger — as plain, framework-free Python functions operating on a SQLite connection.
`tools/` are thin adapters that translate a model-issued function call into a domain
call and shape the result; `agent/` never touches the database directly. This split
also means the trickiest correctness logic (concurrency, idempotency, tax rounding) is
unit-tested with zero network or model dependency.

### Control loop

1. An incoming Telegram message is deduplicated against a `telegram_processed_updates`
   table before any work happens (Telegram delivers at-least-once; a redelivered update
   must be a no-op).
2. A system prompt is rebuilt fresh for every turn — persona, hard rules, the actual
   current date (a model has no reliable notion of "today" on its own), and the shop's
   standing preferences — and sent alongside the full prior conversation.
3. The model replies with either plain text or one or more function calls. Each call is
   dispatched to its tool handler, logged to an audit table, and its result fed back as
   a new turn; this repeats until the model produces a final plain-text reply.
4. A document-generating tool (invoice/deck) pushes the generated file to the chat
   directly as a side effect of the call itself — no separate "pending attachment"
   queue for the rest of the system to manage.
5. `/new` starts a fresh conversation (the model has no memory of what was said before)
   while standing preferences carry over untouched, because they live in their own
   table and are re-read into the system prompt on every turn regardless of
   conversation history.

### Tool surface

29 tools across six modules, each wrapping one domain area:

| Module | Tools |
|---|---|
| `inventory` | find/get/add product, receive stock, adjust stock, low-stock list, reorder suggestions |
| `billing` | open/start/cancel a bill, add/update/remove a line, set payment, get a running summary, finalize |
| `khata` | find/add customer, get balance, list customers with a balance, charge to credit, record a payment |
| `analytics` | daily summary, close the day, sales summary over a date range |
| `preferences` | get/set a standing preference (fixed key set — the model can't invent one nobody reads) |
| `documents` | generate & send an invoice PDF, generate & send an analysis deck |

Every lookup tool (`find_product`, `find_customer`) follows the same contract: it
returns a single confident match, a list of candidates to disambiguate, or a clear
not-found — never a guess. Deciding *whether* to ask a clarifying question and *what*
to ask is left entirely to the model reading that structured result.

`chat_id` — which tenant's data a call can touch — is bound by the dispatcher from the
authenticated Telegram update and is never accepted as a model-supplied argument, even
defensively stripped if a call tries to pass one. Idempotency keys for mutating tools
(finalizing a bill, receiving stock, khata transactions) are likewise derived
server-side from the model's own tool-call id, not left for the model to invent.

## Correctness

| Concern | Mechanism |
|---|---|
| **Grounding** | Prices, stock, and GST slabs never appear in the system prompt — they only enter the conversation via a tool result, so there's structurally nothing to hallucinate from. |
| **Oversell guard** | Stock is decremented with a single atomic `UPDATE ... WHERE qty_on_hand >= ?`, checked by row count. Any short line rolls back the *entire* bill and returns exactly which item and by how much — enforced in SQL, not hoped for in the prompt. |
| **GST correctness** | MRP is treated as tax-inclusive (the correct convention for Indian retail — adding GST on top of MRP double-counts tax). Tax is backed out per line with `Decimal` arithmetic, CGST/SGST split with a reconciling remainder rule so the three figures always sum exactly to the line total, and the bill total rounds to the nearest rupee with an explicit "Round Off" line, matching real invoice convention. |
| **Multi-turn bills** | A bill is a `draft` row until explicitly finalized; every edit operates on the draft, and stock is untouched until that one atomic finalize step. |
| **Idempotency** | Two layers: inbound Telegram updates are deduplicated before they reach the agent, and every mutating tool call carries a server-derived idempotency key checked against a cache table — a repeated call returns the original result rather than re-executing. Finalizing an already-finalized bill is additionally a safe no-op by construction. |
| **Concurrency** | SQLite WAL mode with `BEGIN IMMEDIATE` transactions serializes concurrent writers; combined with the atomic conditional `UPDATE` above, two simultaneous sales — or a sale racing a stock delivery — can't corrupt quantities. Verified with real OS threads against a real file-backed database, not mocked. |
| **Guardrails** | Selling below cost is refused unless explicitly re-confirmed; a stock adjustment requires a reason and can't go negative; charging or settling a khata for an unknown customer is refused outright rather than silently creating one. |
| **Real artifacts** | Invoices are rendered with `reportlab` (pure Python, no system binary dependency); analysis decks use `python-pptx` native chart objects — real, editable PowerPoint charts, not embedded images. |
| **Cross-session memory** | Standing preferences live in their own table, independent of any conversation transcript, and are re-read into the system prompt on every turn — so they survive a `/new` conversation reset and a process restart alike. |

## Project layout

```
config.py                  # env loading
run.py                     # entrypoint: wires everything together, runs Telegram long-polling
db/
  schema.sql                # full schema
  seed.py                    # seed catalog (GST 2.0 rates) and demo customer
  connection.py              # WAL mode, busy-timeout, atomic-transaction helper
domain/                    # pure business logic, no framework dependency, unit-tested directly
  gst.py                      # tax computation, rounding, amount-in-words
  inventory.py / billing.py / khata.py / analytics.py / preferences.py
tools/                     # thin adapters: model call -> domain call -> structured result
agent/
  system_prompt.py            # persona, hard rules, live date, live preferences
  tool_registry.py            # tool schema assembly + dispatch + audit logging
  gemini_client.py            # the tool-calling loop itself
  session_manager.py          # per-chat conversation history, /new handling
documents/                 # PDF invoice + PPTX deck renderers
telegram_bot/               # Telegram handlers, update deduplication
tests/                      # pytest suite, including real-thread concurrency tests
```

## Running it

**Requirements:** Python 3.11+, a Gemini API key, a Telegram bot token (from
[@BotFather](https://t.me/BotFather)).

```bash
python -m venv .venv
.venv/Scripts/activate      # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

cp .env.example .env        # fill in GEMINI_API_KEY and TELEGRAM_BOT_TOKEN

python -m db.seed           # creates and seeds the local SQLite database
pytest                      # 41 tests, no network required

python run.py                # starts the bot (long polling)
```

For local iteration without a Telegram bot, `python -m scripts.repl` opens a terminal
chat against the same agent loop, printing generated-document paths instead of sending
them.

## Tech stack

| | |
|---|---|
| Language | Python 3.13 |
| Model | Google Gemini (`google-genai`), with automatic fallback across a small model list if one's quota is exhausted |
| Storage | SQLite, WAL mode |
| Bot interface | `python-telegram-bot`, long polling |
| Documents | `reportlab` (PDF), `python-pptx` (PPTX with native charts) |
| Tests | `pytest` |
