# Full-Stack Developer Coding Assessment — Submission

| Part   | Contents                                                  | Points |
| ------ | --------------------------------------------------------- | ------ |
| `A/`   | Inventory Reservation Ledger (Python solution + tests)    | 20     |
| `B/`   | Fulfilment Split Optimiser (Python solution + tests)      | 20     |
| `C/`   | Xero Integration Review (`answers.md`)                    | 20     |
| `app/` | Variant PDP — FastAPI backend + React/TypeScript frontend | 40     |

## Setup

Requirements: Python 3.11+, Node 20+.

```bash
# Python parts (A, B, app backend) — one venv covers all of them
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r app/backend/requirements.txt   # fastapi, uvicorn, pytest, httpx

# Frontend
cd app/frontend && npm install
```

## Running the tests

```bash
# from the repository root, with the venv activated
cd A && python -m pytest test_solution.py -q        # 12 tests
cd ../B && python -m pytest test_solution.py -q     # 10 tests (incl. brute-force oracle)
cd ../app/backend && python -m pytest tests/ -q     # 8 API tests
cd ../frontend && npm test                          # 12 frontend tests (vitest)
```

## Running the app

```bash
# terminal 1 — API on http://localhost:8000 (OpenAPI docs at /docs)
cd app/backend && uvicorn app.main:app --reload --port 8000

# terminal 2 — UI on http://localhost:5173 (proxies /api to :8000)
cd app/frontend && npm run dev

# or, from the repo root, both at once:
./run_dev.sh
```

The app seeds one product ("Aurora Merino Hoodie") with Colour × Size options,  
8 SKUs, one unavailable combination (Olive/S) and one out-of-stock SKU (White/M),  
so it is usable immediately.

---

## Task A — Inventory Reservation Ledger

`A/solution.py` reads from stdin (`python A/solution.py < input.txt`).

**Design.** One `Ledger` object holds `on_hand`, `reserved`, per-order reservations  
and a set of processed event ids. Every command is fully validated *before* any  
mutation, so a rejected command never produces a partial state change.  
Idempotency: syntactically valid commands record their `event_id` whether the  
business outcome was OK or REJECTED (per the spec, a rejected business operation  
is still processed); replaying that id returns DUPLICATE with zero state change.  
Syntactically malformed lines (bad verb/arity/qty, non-ASCII ids) are REJECTED  
but *not* recorded — they were never well-formed business operations.

**Output.** `STATUS on_hand reserved` per command; then `OPEN <n>` followed by  
`order_id qty` lines for open reservations, sorted by `order_id` (the spec's  
example ends with `OPEN 0`; the detail lines only appear when n > 0 — this is  
the one place the spec is ambiguous, documented here as an assumption).

**Complexity.** O(N) time, O(distinct orders + processed events) memory; every  
operation is a dict/set lookup. The 200k-command test completes in well under a  
second.

## Task B — Fulfilment Split Optimiser

`B/solution.py` reads from stdin (`python B/solution.py < input.txt`).

**State.** Warehouses sorted by id; suffix DP  
`suff[i][c][q]` = min cost using warehouses `i..W-1`, exactly `c` of them,  
allocating exactly `q` units. Transition per warehouse: skip it, or take  
`x ∈ [1, min(stock, q)]` units at `fixed + x·unit`.

**Key optimisation.** The inner min over `x` is rewritten as a sliding-window  
minimum of `g[m] = suff[i+1][c-1][m] − unit·m` over `m ∈ [q−stock, q−1]`,  
evaluated with a monotone deque — O(Q) per (warehouse, count) row instead of  
O(Q·stock). This is what makes the largest cases (W=30, Q=2000) fast; a subset  
brute force (2³⁰) is not viable.

**Tie-breaking.** Primary key = fewest warehouses (first feasible `c` in  
ascending order), secondary = min cost (already what the DP stores). The  
lexicographic tie-break is handled by greedy reconstruction over the suffix  
table: walking warehouses in id order, including warehouse `i` (any `x ≥ 1`)  
always yields a lexicographically smaller list than skipping it (its id is  
smaller than whatever comes next), and among feasible `x` the smallest wins  
(same id, smaller quantity). Each candidate is verified exactly against  
`suff[i+1][·][·]`, so the (count, cost) optimum is preserved.

**Complexity.** Time O(W²·Q), space O(W²·Q) stored as `array('q')` (~15 MB at  
the limits). Tests include a brute-force oracle cross-checked over 300 random  
small cases, plus impossible orders, zero-stock warehouses, equal-cost ties and  
the exact-stock boundary.

## Task C — Xero Integration Review

See `C/answers.md`. Covers connection verification, a 401/403/404 diagnostic  
tree, resumable incremental sync (If-Modified-Since + paging + cursor  
persistence), 429 handling with `Retry-After`/jitter/retry budgets, duplicate  
invoice prevention, and observability/security, with links to the official Xero  
developer documentation.

---

## App — Variant PDP

### API contract

Base URL `http://localhost:8000`. All errors share one shape:  
`{"error": {"code": "...", "message": "...", "details": {...}?}}`.

**`GET /api/products/{id}`** → 200

```json
{
  "id": "p1", "name": "Aurora Merino Hoodie", "description": "...",
  "images": ["/img/hoodie-black.svg"],
  "options": [{"name": "Colour", "values": ["Black","White","Olive"]},
              {"name": "Size", "values": ["S","M","L"]}],
  "skus": [{"id": "SKU-BLA-M", "price_cents": 8900, "stock": 12,
            "image": "/img/hoodie-black.svg",
            "options": {"Colour": "Black", "Size": "M"}}]
}
```

404 `PRODUCT_NOT_FOUND` for unknown ids.

**`POST /api/cart/items`** — header `Idempotency-Key: <uuid>` (required),  
body `{"sku_id": "SKU-BLA-M", "quantity": 2}` → 201

```json
{
  "item": {"sku_id": "SKU-BLA-M", "quantity": 2, "unit_price_cents": 8900},
  "stock_remaining": 10,
  "cart": {"items": [...], "total_items": 2, "total_price_cents": 17800}
}
```

Error codes: 400 `INVALID_INPUT` (schema), 400 `MISSING_IDEMPOTENCY_KEY`,  
404 `SKU_NOT_FOUND`, 409 `INSUFFICIENT_STOCK` (with `details.available`),  
409 `IDEMPOTENCY_KEY_MISMATCH` (same key, different payload),  
500 `INTERNAL_ERROR` (unexpected; internals never leak).

**`GET /api/cart`** → 200 `{"items": [...], "total_items": n, "total_price_cents": n}`.

### Backend decisions

- **Never trust the client**: price comes from the server-side SKU; quantity  
  and stock are validated server-side.
- **Idempotency**: the first execution's `(payload hash, status, body)` is  
  stored under the key; a replay returns the stored response unchanged (no  
  double add), a key reused with a different payload is 409.
- **Oversell prevention**: adding to cart *reserves* stock — the stock check  
  and decrement happen inside one `asyncio.Lock` critical section together  
  with the idempotency check, so two concurrent requests for the final unit  
  serialise and exactly one wins (proved by the race test). The store is  
  per-process (see limitations); the endpoint code is storage-agnostic and the  
  lock maps 1:1 onto an atomic  
  `UPDATE sku SET stock = stock - :q WHERE id = :id AND stock >= :q`  
  rowcount check when moved to SQLite/Postgres.
- Money is integer cents everywhere (no float rounding).

### Frontend decisions

- **Layering**: `api/` (typed fetch, `ApiError`), `domain/` (pure variant  
  resolution — `resolveSku`, `isValueAvailable`, `clampQuantity`), UI in  
  `components/`. No `any` in the codebase.
- **Variant UX**: impossible combinations are derived from the SKU list and  
  disabled (Olive → S disabled); option changes re-resolve the SKU and update  
  price/image/stock from server data; quantity is clamped to the new SKU's  
  stock on every change.
- **Duplicate submission**: the button disables while a request is in flight  
  *and* each attempt sends an `Idempotency-Key` (one key per attempt; a new  
  user action mints a fresh key), so accidental double-clicks are stopped  
  client-side and retries are safe server-side.
- **States**: loading, retryable load error, incomplete selection, unavailable  
  combination, out-of-stock, adding/success/validation/insufficient-stock/  
  server-error — all covered. Feedback uses `role="alert"`/`role="status"`  
  with `aria-live`, options are real buttons with `aria-pressed`, focus is  
  visibly outlined.
- **Network realism**: after a successful add, the displayed stock is replaced  
  by the server's authoritative `stock_remaining`, so newer server-side stock  
  is reflected without a page refresh; load failures offer retry.
- **Responsive**: single column at 375 px, two columns from 768 px up.

### Assumptions and known limitations

- Single global cart (no auth/sessions — out of scope per the brief).
- In-memory store: state resets on restart and is not shared across multiple  
  worker processes; run uvicorn with one worker. The API surface is  
  storage-agnostic (see oversell note above). The idempotency-key and cart
  dictionaries grow without bound (no TTL/eviction) — a production store
  should persist them and expire old keys.
- Cart reservations never expire (no checkout flow to release them).
- The `OPEN` output format for Task A when reservations remain is an  
  assumption (`OPEN <n>` then sorted `order_id qty` lines); the spec example  
  only shows the `OPEN 0` case.
- Prices are display-formatted as USD; a production app would localise.

## AI assistance disclosure

This submission was produced with AI-assisted drafting of code,  
tests and documentation. All design decisions — the Task B sliding-window DP  
and greedy lexicographic reconstruction, the Task A idempotency semantics, the  
reservation-based oversell strategy, and the Xero integration answers — were  
reviewed and verified by running the full test suites locally, and can be  
explained and modified live.
