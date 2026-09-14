# Supermarket Ops Agent — Nebula KnowLab Take-Home — Full Build Plan

## Context

Nebula KnowLab's take-home asks for a Telegram-only conversational agent that runs a small
Indian kirana store end-to-end (stock-in, billing, GST, khata/credit, daily close, PDF
invoices, PPTX analysis decks, cross-session memory) with **zero regex/intent routing** — the
model must own the reasoning, and business rules (oversell guard, GST math, idempotency,
concurrency, khata integrity) must live in the tool/data layer, not the prompt. Grading
explicitly rewards two things: (1) evidence the domain was actually understood (real SKUs,
correct GST, loose vs packaged units), and (2) a deliberately designed skill/tool surface
rather than a thin wrapper around a big if/elif router. Submission is due 5 calendar days
from receipt and requires a live, reachable Telegram bot, a recording, and a private GitHub
repo with specific collaborators.

This is a greenfield project (empty working directory). Before writing this plan I verified
two things that materially change what a naive plan would get wrong:

1. **Claude Agent SDK facts** (via the SDK docs, not recalled from training): custom domain
   tools are added as *in-process MCP servers* (`create_sdk_mcp_server` + `@tool`); the
   built-in coding tools (Bash/Read/Write/etc.) can be fully disabled (`tools: []`); a
   `PreToolUse` hook can hard-deny a tool call before it runs; sessions are per-conversation
   and persisted as resumable transcripts; and **there is no built-in cross-session memory
   feature** — "memory across chats" is something we must build ourselves against our own
   DB. This lines up naturally with the brief's own requirement that memory "lives outside
   the context window."
2. **GST reality**: India's GST Council rationalized rates effective **2025-09-22** ("GST
   2.0") from a four-slab system (0/5/12/18/28%) down to essentially **nil, 5%, 18%, 3%
   (gold/silver), and a 40% demerit rate** for luxury/sin goods. The brief's own example
   ("FMCG like chocolates/soaps 12–18%") reflects the *old* slab structure — soaps and
   chocolates are 5% now; detergents (Surf Excel, HSN 3402) stayed at 18%. Per your
   decision, the seed catalog uses the **current real rates**, and GST is modeled as
   per-product data (HSN + rate), not a hardcoded prompt fact — so this is a seed-data
   choice, not an architectural one, and is trivially correctable later.

Decisions locked in with you: **Python** implementation, **GST 2.0 real rates**, hosting
platform **deferred until after local development** (this plan makes local dev fully
self-sufficient — Telegram long-polling works from any machine with outbound internet, so
"running locally" and "running in production" are the same process pointed at the same kind
of SQLite file; only the *where* changes later).

**Harness pivot #1 (post Phase 1):** no Anthropic API access was available, so the harness moved
from Claude Agent SDK to a hand-rolled tool-calling loop. This is still brief-compliant — the
brief says "any modern agent harness... or equivalent." The pivot only touches the *agent*
layer: **the entire `domain/` layer from Phase 1 is unchanged and provider-agnostic** — the
oversell guard, GST math, idempotency, and khata rules were already proven correct against
plain SQLite transactions, independent of any LLM. What's lost by not using Claude Agent SDK is
convenience, not correctness: no built-in session-resumption (we persist the message list
ourselves in `agent_messages`) and no `PreToolUse` hard-deny hook (irrelevant anyway — the
authoritative enforcement was always in `domain/`'s atomic SQL, never in a hook).

**Harness pivot #2:** first tried Mistral (`mistralai` SDK) — code-complete and verified reaching
the API correctly, but the available account had no usable quota (persistent 429 across two keys
and every model tier, even after backoff). Moved to **Google Gemini** (`google-genai` SDK, the
official current package), whose free tier proved to have a real, documented, workable quota
(5 requests/minute per model on `gemini-3.6-flash` — confirmed empirically, including a live
multi-tool bill-build-and-finalize round trip with correct GST math end to end). `tools/*.py`
were untouched by this second pivot (they only depend on the provider-agnostic `ToolSpec`
contract); only `agent/{mistral,gemini}_client.py` and the `agent_messages` schema changed,
since Gemini's message shape is meaningfully different (see §7).

---

## 1. Harness choice and why

**A hand-rolled agent loop (Python) against the Gemini API** (`google-genai` SDK), driving one
persisted message-history per Telegram chat, with a flat tool registry (JSON-schema function
declarations) wrapping every `domain/*.py` module. No MCP, no LangGraph.

Why this over other options:
- Gemini's native function calling (`types.Tool(function_declarations=[...])` on
  `generate_content`) gives the same shape of loop regardless of provider: the model decides
  when to call a tool, we execute it and feed back a result, loop until it returns plain text.
  This *is* the "observe → reason → act → feed result back → continue" control loop the brief
  asks for — just written explicitly instead of provided by an SDK. Confirmed empirically: a
  single natural-language "make a bill: 2kg sugar, 1 aashirvaad atta 5kg, 4 maggi, UPI" message
  correctly chained `start_bill → add_bill_item ×3 → set_payment → finalize_bill` and returned a
  bill with exactly correct GST figures.
- Explicitly **not** a LangGraph node-per-command graph (the brief calls this out as a
  misread): there is exactly one agent here, reasoning freely over a flat, well-named tool
  surface. No per-intent nodes, no manual routing graph.
- No subagents, same reasoning as before: one continuously-running conversation about one
  shop's books shouldn't be fragmented across agents for no benefit.
- Session persistence is now our own responsibility: `agent_messages` stores the full message
  list per `(chat_id, generation)`; `/new` bumps `generation` rather than deleting history, so
  old messages are excluded from context but kept for audit — the literal mechanism for "memory
  lives outside the context window" the brief asks for.
- Operational note for the README: the free tier is rate-limited (5 req/min/model) — fine for a
  human texting the bot at a natural pace, but a rapid multi-tool chain can burn several requests
  in one turn. Worth a line in the demo recording notes and a candidate for a paid-tier bump
  before the review window if it causes friction.

---

## 2. Repository layout

```
nebula-supermarket-agent/
├── README.md                       # harness+why, control loop, tool design, hard-parts writeup
├── .env.example                     # GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, DB_PATH, SHOP_* defaults
├── pyproject.toml / requirements.txt
├── run.py                          # entrypoint: builds Application + SessionManager, run_polling()
├── config.py                       # env loading
├── db/
│   ├── schema.sql                  # full DDL (section 4)
│   ├── seed.py                     # seeds products/customers per section 6
│   └── connection.py               # WAL pragma, busy_timeout, BEGIN IMMEDIATE helper
├── domain/                         # pure business logic, framework-agnostic, unit-testable
│   ├── gst.py                      # slab lookup, tax-inclusive back-calc, rounding, amount-in-words
│   ├── inventory.py                # add_product, receive_stock, adjust_stock, low_stock/reorder
│   ├── billing.py                  # bill lifecycle + atomic finalize (the concurrency-critical file)
│   ├── khata.py                    # customer credit ledger
│   ├── analytics.py                # daily/weekly aggregates + rule-based insight generation
│   └── preferences.py              # get/set with a fixed allowed-key schema
├── documents/
│   ├── invoice_pdf.py              # reportlab GST invoice renderer
│   └── analysis_deck.py            # python-pptx deck w/ native charts
├── tools/                          # thin adapters: parse args -> call domain/* -> shape a tool result
│   ├── inventory_tools.py
│   ├── billing_tools.py
│   ├── khata_tools.py
│   ├── analytics_tools.py
│   ├── document_tools.py
│   └── preference_tools.py
├── agent/
│   ├── system_prompt.py            # persona + hard rules + dynamic preferences snapshot
│   ├── tool_registry.py            # ToolSpec dataclass, JSON-schema conversion, name->handler dispatch
│   ├── gemini_client.py            # the tool-calling loop: send -> function_calls? -> execute -> feed back -> repeat
│   └── session_manager.py          # chat_id+generation message history, /new handling
├── telegram_bot/
│   ├── handlers.py                 # message/command handlers, update_id dedupe
│   └── attachments.py              # send_document/send_photo helper, injected into doc tools
└── tests/
    ├── test_gst.py
    ├── test_billing_concurrency.py # concurrent finalize() calls must never oversell
    ├── test_idempotency.py         # duplicate finalize/receive_stock calls are no-ops
    └── test_khata.py
```

Why domain/ is separate from tools/: business rules must live "in the skills/tools, not the
prompt" — but they should also be unit-testable without spinning up a model or Telegram. The
`domain/` modules contain 100% of the logic and DB transactions; `tools/` are thin translators
between a model-issued tool call and a domain function call. This also means the tricky
correctness tests (concurrency, idempotency, GST rounding) can run in plain pytest with no
network/model
calls at all.

---

## 3. Tool surface (the part that's actually graded)

Six tool modules (inventory, billing, khata, analytics, documents, preferences), each exporting
a flat list of `ToolSpec(name, description, json_schema, handler)`. `agent/tool_registry.py`
merges them into the single `types.Tool(function_declarations=[...])` sent on every Gemini
request, and dispatches an incoming function call by name back to its handler. There is no
other way for the model to touch the store — no filesystem, no shell, nothing but these
functions.

**inventory**
- `find_product(query)` — fuzzy name/alias match; returns candidates (id, name, unit, price,
  stock) or a `needs_clarification` payload when the match is ambiguous or absent.
- `get_product(product_id)`
- `add_product(name, unit, is_loose, hsn_code, gst_rate, cost_price, mrp, reorder_level,
  opening_qty)` — refuses duplicate name+unit; refuses a `gst_rate` outside the configured
  slab set.
- `receive_stock(product_ref, qty, cost_price, mrp?, supplier?, idempotency_key)` — atomic
  stock increment; can update cost price; idempotent by key.
- `adjust_stock(product_id, delta, reason)` — manual correction (breakage/expiry); reason is
  mandatory and logged; **cannot** take stock negative (same guard as a sale).
- `list_low_stock()` / `get_reorder_suggestions()` — reorder-level breach *and* sales-velocity
  based "days of stock left" (stretch, see §9).

**billing**
- `get_open_bill()` — returns the chat's current draft if one exists (chat_id is bound
  server-side from the Telegram update, never a model-supplied argument — a tenant-isolation
  boundary, not just a convenience).
- `start_bill(customer_ref?)`
- `add_bill_item(bill_id, product_ref, qty, unit)` — resolves product, snapshots
  price/GST at add-time, advisory stock check (real check happens at finalize).
- `update_bill_item_qty(bill_id, line_ref, new_qty)`, `remove_bill_item(bill_id, line_ref)` —
  the "drop the butter, make it 6 Maggi" edit path.
- `set_bill_payment(bill_id, mode, reference?)`
- `get_bill_summary(bill_id)` — full running tax breakup, for "what's the bill so far".
- `finalize_bill(bill_id, idempotency_key)` — the one hard-parts-critical tool; see §5.
- `cancel_bill(bill_id)`

**khata**
- `find_customer(name)` — same ambiguity contract as `find_product`; a genuinely unknown name
  returns a clear not-found result, never a silent auto-create.
- `charge_to_credit(customer_ref, amount, bill_id?)`
- `record_khata_payment(customer_ref, amount, mode, reference?)` — flags (doesn't silently
  allow) an overpayment past zero balance.
- `get_khata_balance(customer_ref)`, `list_khata_customers(min_balance?)`

**analytics**
- `get_daily_summary(date?)` — totals, CGST/SGST collected, cash/UPI/card/credit split, top
  items.
- `close_day(date?)` — marks a day closed (blocks backdated edits to that day's bills).
- `get_sales_range_summary(start_date, end_date)` — feeds the analysis deck.

**documents**
- `generate_invoice_pdf(bill_id)` — must be a finalized bill; renders and sends the PDF
  directly to the Telegram chat (see §7), returns a short confirmation string to the model.
- `generate_analysis_deck(start_date, end_date)` — same send-directly pattern for the PPTX.

**preferences**
- `get_preferences()`
- `set_preference(key, value)` — validated against a fixed allowed-key enum (default payment
  mode, default brand mappings like "atta" → SKU, shop name, GSTIN, address, invoice footer)
  so the model can't invent keys nobody ever reads.

**Ambiguity contract (how clarification stays model-owned, not a router):** any tool that
resolves a name to an id returns one of three shapes — a single confident match, a
`needs_clarification` result carrying the candidate list, or a not-found result. The tool
only ever answers "how many plausible matches exist" (a factual lookup); it never decides
*whether* to ask, *what* to ask, or picks on the model's behalf. The model reads the
candidates/context (e.g. a "default atta" preference) and decides whether to just proceed or
ask the owner — that decision is the reasoning step the brief requires to come from the
model.

---

## 4. Data model (SQLite, WAL mode)

```sql
products(id, name, aliases, unit, is_loose, hsn_code, gst_rate, price_includes_tax,
         cost_price, sell_price, qty_on_hand, reorder_level, created_at, updated_at)
stock_movements(id, product_id, delta, reason, ref_type, ref_id, idempotency_key UNIQUE, created_at)
customers(id, name, aliases, phone, balance, created_at)
khata_transactions(id, customer_id, type, amount, mode, reference, bill_id, idempotency_key UNIQUE, created_at)
bills(id, chat_id, customer_id NULL, status, payment_mode, payment_ref,
      subtotal, cgst_total, sgst_total, round_off, grand_total,
      idempotency_key UNIQUE, created_at, finalized_at)
bill_lines(id, bill_id, product_id, description_snapshot, unit, qty,
           unit_price_snapshot, gst_rate_snapshot, taxable_value, cgst_amount, sgst_amount, line_total)
preferences(key PRIMARY KEY, value, updated_at)
telegram_processed_updates(update_id PRIMARY KEY, chat_id, processed_at)
idempotency_keys(tool_name, key, result_json, created_at, PRIMARY KEY(tool_name, key))
agent_sessions(chat_id PRIMARY KEY, generation INTEGER DEFAULT 1, updated_at)
agent_messages(id, chat_id, generation, role['user'|'model'], parts_json, created_at)
audit_log(id, chat_id, tool_name, tool_input_json, decision, created_at)
```

`price_includes_tax` defaults true (MRP is tax-inclusive for packaged retail — the correct
convention for Indian retail billing; naively adding GST on top of MRP double-counts tax,
which is a common mistake this design deliberately avoids).

---

## 5. Hard parts — mechanism, not hand-waving

| # | Requirement | Mechanism |
|---|---|---|
| 1 | Grounding | Catalog/prices/stock are **never** embedded in the system prompt — they only enter context via a tool result. There is structurally nothing for the model to hallucinate from; the system prompt also explicitly instructs it to never state a number from memory. |
| 2 | Oversell guard | `finalize_bill` runs one `BEGIN IMMEDIATE` transaction; each line does `UPDATE products SET qty_on_hand = qty_on_hand - ? WHERE id=? AND qty_on_hand >= ?` and checks `rowcount == 1`. Any failing line rolls back the *whole* bill (all-or-nothing) and returns a structured "short by N" error naming the item — enforced in SQL, not the prompt. |
| 3 | GST correctness | Per line: `line_gross = unit_price * qty` → back out tax (`line_gross / (1+rate/100)`) rather than adding tax on top of MRP; CGST=SGST=tax/2, rounded to paise with a reconciling remainder rule so the three numbers always sum exactly to the gross; bill-level "Round Off" line rounds the final payable to the nearest rupee, matching real Indian invoice convention. |
| 4 | Multi-turn bills | `bills.status` is `draft` until `finalize_bill`; every add/remove/update tool operates on the draft row; stock is untouched until finalize. |
| 5 | Idempotency | Two layers: (a) `telegram_processed_updates` dedupes redelivered Telegram updates before they ever reach the agent; (b) every mutating tool takes an `idempotency_key`, checked against `idempotency_keys (tool_name, key)` — a repeat call returns the cached result without re-executing. `finalize_bill` is additionally idempotent by construction (`status` check: finalizing an already-finalized bill is a no-op). |
| 6 | Concurrency | SQLite WAL + `busy_timeout` + `BEGIN IMMEDIATE` serializes writers; the atomic `UPDATE ... WHERE qty_on_hand >= ?` pattern above makes a concurrent sale-vs-sale or sale-vs-stock-in race safe without external locking. |
| 7 | Guardrails | "Below cost" checked in `finalize_bill` (line unit_price vs `cost_price`) → returns a confirm-needed result, not a silent sale; `adjust_stock` requires a reason and can't go negative; `record_khata_payment`/`charge_to_credit` refuse an unknown customer_ref outright (khata tools never auto-create a customer). |
| 8 | Real artifacts | `reportlab` (pure-Python, no system binary dependency) for the invoice; `python-pptx` native chart objects (`CategoryChartData` + `add_chart`) for the deck — real editable PowerPoint charts, not embedded screenshots. |
| 9 | Cross-session memory | `preferences` table, fetched fresh and appended into the system prompt at the start of every session (including after `/new`), plus a live `get_preferences`/`set_preference` tool pair so it's also readable/writable mid-conversation. `agent_messages` (conversation transcript) is continuity only — never where business memory lives. |

---

## 6. Seed catalog (GST 2.0 rates, per your decision)

| Product | Unit | HSN | GST | Note |
|---|---|---|---|---|
| Loose Atta / Rice / Toor Dal / Sugar | per kg | — | 0% | loose staple, nil-rated |
| Tata Salt 1kg | packet | 2501 | 0% | edible salt, nil-rated |
| Aashirvaad Atta 5kg | packet | 1101 | 5% | packaged staple |
| Amul Butter 100g | packet | 0405 | 5% | moved 12%→5% in GST 2.0 |
| Fortune Sunflower Oil 1L | bottle | 1512 | 5% | edible oil |
| Maggi 70g | packet | 1902 | 5% | moved 12%→5% (instant noodles) |
| Parle-G | packet | 1905 | 5% | moved 18%→5% (biscuits) |
| Surf Excel | packet | 3402 | 18% | detergent — did **not** move in GST 2.0 |
| Demo khata customer: Ramesh | — | — | — | for the credit-cycle demo |

README will state plainly: HSN→slab mapping here is illustrative seed data reflecting the
2025-09-22 rationalization as best documented at plan time, not a certified tax reference —
the engine is data-driven specifically so this is correctable without touching code.

---

## 7. Control loop & session lifecycle

1. `python-telegram-bot` (v21+, async, long-polling) receives an update → check
   `telegram_processed_updates`; skip if already seen; else record it.
2. `SessionManager.handle_message(chat_id)`: reads `agent_sessions.generation` and every
   `agent_messages` row for that `(chat_id, generation)`, rebuilding the Gemini `contents` list
   to send. The system instruction is always freshly built by `system_prompt.py` (persona +
   hard rules + current `preferences` snapshot) and passed as `GenerateContentConfig.
   system_instruction` — never itself persisted as a Content, so a changed preference is
   picked up even without a `/new`.
3. `/new` command (our Telegram-side equivalent of the demo's "/new chat"): increments
   `agent_sessions.generation` for that chat. Old `agent_messages` rows stay in the DB (audit
   trail) but are excluded from the next history load — transcript memory is gone,
   `preferences` memory is not, because it's re-fetched fresh into the next turn's system
   prompt regardless of generation.
4. The turn loop (`agent/gemini_client.py`): send `contents` + the `Tool(function_declarations
   =[...])` to `generate_content(...)`; if the response has `function_calls`, execute each via
   `tool_registry.dispatch(name, args)` (calls the matching `tools/*.py` handler, which catches
   `DomainError` into a structured error payload), pack all results into one `role="user"`
   Content of `function_response` parts, and loop; once the response has plain text with no
   function calls, that is the assistant's reply. Every Content produced (the user's message,
   each model turn, each function-result turn) is persisted to `agent_messages` as it occurs.
5. Document tools (`generate_invoice_pdf`, `generate_analysis_deck`) have the chat's `bot` +
   `chat_id` injected by closure, so they push the file to Telegram directly as a side effect
   and return a one-line confirmation to the model — no separate "pending attachment" queue.
6. Bot sends the assistant's text reply.

---

## 8. Day-by-day plan (5 calendar days)

- **Day 1** — repo scaffold, `db/schema.sql` + `seed.py`, all of `domain/` with unit tests
  (GST rounding, atomic stock decrement, idempotency) passing against plain pytest — no model
  or Telegram involved yet, so the hardest correctness logic is nailed down first. ✅ done.
- **Day 2** — wrap `domain/` in the six tool modules; wire `agent/` (system prompt, tool
  registry, Gemini tool-calling loop, session manager); verified live against the real Gemini
  API from a terminal harness (no Telegram yet) — a full natural-language multi-item bill build
  + finalize round-tripped correctly with exactly-correct GST figures. ✅ done (after a harness
  detour: Claude → Mistral → Gemini, see the pivot notes above; `domain/` and `tools/` were
  untouched by either pivot).
- **Day 3** — Telegram integration (`telegram_bot/`), full run.py; manually run every §3
  scenario end-to-end locally (receive stock → multi-item bill with an edit → oversell guard
  → khata cycle → preference set → `/new` → preference remembered).
- **Day 4** — `documents/` (PDF invoice, PPTX deck with native charts); polish system prompt
  based on Day 3 friction; write concurrency test simulating two simultaneous `finalize_bill`
  calls.
- **Day 5** — deploy (platform decision resumes here — Railway/Fly.io/own VPS, whichever you
  land on, per the hosting question we deferred), record the 4–5 min demo, write the README,
  create the private GitHub repo, invite `Aswath363`, `akshaiP`, `ashwanthnebula`.

---

## 9. Stretch, priority-ordered (only after §8 core is solid)

1. **Reorder suggestions from sales velocity** — cheapest to add: rolling avg daily
   consumption per SKU from `bill_lines` over the last 14 days → `days_left = qty_on_hand /
   avg_daily_qty`, folded into `get_reorder_suggestions`. No new schema.
2. **Branded invoice PDF** — logo/letterhead from a `preferences` value; easy visual win.
3. **Hindi/Hinglish** — largely free: Claude is natively multilingual/code-mixing; mainly
   needs the system prompt to explicitly permit and expect Hindi/Hinglish shopkeeper phrasing.
4. **Expiry/batch + FEFO** — real scope add (a `batches` table, FEFO consumption order at
   sale time); only if Days 1–4 finish early.
5. Voice notes — lowest priority given the time budget (needs Telegram voice download +
   transcription infra); skip unless everything else is done with time to spare.

---

## 10. Deliverables checklist

- [ ] Live, reachable Telegram bot (handle in README), kept running through review
- [ ] Claude Agent SDK harness, custom tools only, no coding tools exposed
- [ ] PDF invoice generation (reportlab)
- [ ] PPTX analysis deck with native charts (python-pptx)
- [ ] README (~1 page): harness+why, control loop, tool design, hard-parts table
- [ ] 4–5 min recording following the exact flow in the brief
- [ ] Private GitHub repo, collaborators `Aswath363`, `akshaiP`, `ashwanthnebula`, clean
      progressive commit history (roughly one commit cluster per day above, not one mega-commit)

---

## 11. Verification plan

- `pytest tests/` — GST rounding edge cases (e.g. odd-paise reconciliation), concurrent
  `finalize_bill` calls against a shared in-memory/temp-file SQLite DB asserting no
  oversell, duplicate idempotency-key calls asserting single effect.
- Manual scripted run-through of every §3 tool via a terminal harness before wiring Telegram,
  to isolate tool-logic bugs from bot-plumbing bugs.
- Full manual pass of the exact demo script (§8, Day 3) against the real Telegram bot before
  recording, so the recording is a rehearsed run, not a first attempt.
