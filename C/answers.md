# Task C — Xero Integration Review

**Assumptions.** OAuth 2.0 authorisation-code flow with `offline_access` (refresh tokens);
Xero Accounting API v2 (`https://api.xero.com/api.xro/2.0`), JSON responses; each connected
organisation is one *tenant* identified by a `tenantId`, stored with its own token set and
sync cursor. SDK choice is irrelevant to the answers below; everything is stated at the
HTTP level so it holds for any SDK.

**Docs relied on:**
- OAuth 2.0 flow & scopes — https://developer.xero.com/documentation/guides/oauth2/overview/
- Connections endpoint & `xero-tenant-id` — https://developer.xero.com/documentation/guides/oauth2/auth-flow/ (and the API reference for `GET /connections`)
- Rate limits & headers — https://developer.xero.com/documentation/best-practices/api-call-efficiencies/rate-limits and https://developer.xero.com/faq/limits
- Requests & responses (If-Modified-Since, paging, where) — https://developer.xero.com/documentation/api/accounting/requests-and-responses
- Invoices endpoint — https://developer.xero.com/documentation/api/accounting/invoices

---

## C1 — Connection verification

Smallest sequence that proves OAuth and tenant selection work *before* touching invoices:

1. **Load the stored token set for the organisation; check expiry locally.**
   If `expires_at < now + skew(60s)`, refresh first (see step 2).
   *Proves:* we are not about to send a request we already know will 401.

2. **`POST https://identity.xero.com/connect/token` with `grant_type=refresh_token`** (only when needed).
   - 200 + new token set → client credentials and refresh token are valid.
     Persist the *new* refresh token immediately — Xero rotates refresh tokens,
     and the old one is dead from this point.
   - 400 `invalid_grant` → the connection was revoked or the refresh token was
     already rotated elsewhere. Mark the connection `needs_reauth` and stop;
     no amount of retrying will fix it.

3. **`GET /connections` with the access token.**
   - 200 → the access token itself is valid (proves OAuth, independent of any tenant).
   - Assert the stored `tenantId` is present in the returned list. If it is absent,
     the user disconnected that organisation — mark `needs_reauth`, do not attempt invoice calls.
   - 401 → token invalid/expired despite our local check (clock skew, revocation) → refresh once, retry once, then fail the connection check.

4. **One cheap tenant-scoped probe: `GET /api.xro/2.0/Organisation` with header `xero-tenant-id: <tenantId>`.**
   - 200 → tenant selection works end-to-end: token + tenant header + the
     `accounting.settings` scope are all correct, and this is the cheapest
     tenant-scoped read available.
   - 403 → token valid but missing scope / tenant not authorised for this app.

Only after steps 1–4 pass do we start invoice sync. Each step isolates a distinct failure
domain (credentials → token validity → tenant membership → tenant-scoped authorisation),
so the first failing step names the problem.

---

## C2 — Failure diagnosis: invoices call returns 401 / 403 / 404

`GET /connections` succeeds, but `GET /api.xro/2.0/Invoices` fails differently per environment:

```
Invoices request failed
│
├─ 401 Unauthorized
│   ├─ Access token expired and local expiry check was bypassed/skewed?
│   │    → refresh once, retry once.
│   ├─ Still 401 after a fresh token?
│   │    → token issued for a different client (wrong client_id/secret in this env),
│   │      token truncated/corrupted in storage, or revoked.
│   │    → verify env config: client_id, token storage namespace (per-tenant key
│   │      collision is a classic multi-tenant bug: tenant A's invoices requested
│   │      with tenant B's token still passes /connections for B but fails here).
│   └─ Check WWW-Authenticate header and Xero-Correlation-Id for support escalation.
│
├─ 403 Forbidden
│   ├─ Token is valid but lacks the scope: invoices need
│   │    accounting.transactions (or accounting.transactions.read for read-only).
│   │    → decode the JWT and inspect granted scopes; a scope mismatch means the
│   │      consent screen in that env granted different scopes (check the
│   │      `scope` parameter in the authorise URL per environment).
│   ├─ xero-tenant-id header missing or names a tenant not in /connections
│   │    → this is the usual cause of "works in dev, 403 in prod".
│   └─ App/tenant combination not authorised (uncertified app > 25 connections,
│      or the connection was created by a different app).
│
└─ 404 Not Found
    ├─ Wrong base URL / path for the environment (e.g. hitting a partner-only
    │    path, typos like /Invoice, or a stale proxy/ingress rule in one env).
    ├─ GET by id: /Invoices/{guid} 404 means that invoice does not exist *in this
    │    tenant* — usually a tenant-ID mix-up (invoice id from tenant A queried
    │    against tenant B), or the record was deleted/archived.
    └─ Distinguish "endpoint 404" (HTML/empty body, whole env broken → config)
       from "resource 404" (JSON error body, single record → data/tenant issue).

In all cases: log status + Xero-Correlation-Id + tenant + endpoint (no tokens!),
fix the config/scope/tenant mapping, then re-run. 401→refresh-retry is the only
automatic remediation; 403/404 are configuration problems — retrying changes nothing.
```

---

## C3 — Incremental synchronisation

Goal: a resumable invoice sync for a large organisation.

**Cursor.** Per `(tenant_id, endpoint)` persist: `last_modified_since` (UTC timestamp),
`page`, `job_id`, `status`. The cursor row is updated transactionally with the data
writes (same DB transaction as the upserted invoices), so a crash can never advance
the cursor past data we failed to store.

**Change window.** Send `If-Modified-Since: <last_modified_since>` (UTC, second
precision) so Xero returns only invoices with `UpdatedDateUTC` at/after the watermark.
Use a small overlap (e.g. watermark − 5 minutes) and rely on idempotent upserts to
absorb duplicates — this covers in-flight updates racing the watermark and clock skew.
Note: Xero documents changes that do **not** bump `UpdatedDateUTC` (e.g. some fields on
partially paid transactions, derived contact balances), so schedule a periodic full
reconciliation pass (nightly/weekly) instead of trusting the incremental stream forever.

**Pagination.** Invoices support `?page=N` (100 records per page; paging also returns
line items that the unpaged list omits). Loop pages until an empty page. Persist `page`
after each completed page so a worker crash resumes mid-sync, not from page 1.

**Duplicates.** Upsert by Xero `InvoiceID` (GUID) with a unique constraint; the same
invoice appearing in overlapping windows is a no-op update. Never key on
`InvoiceNumber` alone for the internal mirror — GUID is the stable identity.

**Partial failure.** A page can fail halfway through processing its 100 invoices:
process each page in one DB transaction (page succeeds atomically or not at all), so
replaying a page is safe. If the page is genuinely poisoned (one bad record), fall back
to per-record transactions for that page, quarantine the failing `InvoiceID` with its
error, and continue — one bad invoice must not stall the whole tenant.

**Safe replay.** Re-running the whole job with the same cursor is always safe:
watermark overlap + GUID upserts make the sync naturally idempotent. Resetting the
cursor to an earlier date triggers a backfill that converges to the same state.

**Rate awareness.** Read `X-MinLimit-Remaining`/`X-DayLimit-Remaining` on every
response; stop scheduling new pages for a tenant when the daily budget is nearly
exhausted (resume tomorrow) rather than slamming into 429s.

---

## C4 — Rate limits (HTTP 429)

Xero's per-tenant limits: **60 calls/minute**, **5,000 calls/day** (1,000 on the
Starter tier), **5 concurrent calls in progress**; plus an app-wide 10,000 calls/minute
across all tenants. 429 responses carry `X-Rate-Limit-Problem` (`minute` / `day` /
possibly `concurrent`) and, for minute/day limits, `Retry-After: <seconds>`. Successful
responses carry `X-MinLimit-Remaining`, `X-DayLimit-Remaining`, `X-AppMinLimit-Remaining`.

Behaviour of the worker:

1. **Honour `Retry-After` exactly** for minute/day 429s — it is the only reliable
   signal since windows are fixed and reset at different times per tenant. Concurrent-limit
   429s have no `Retry-After`: back off briefly (start ~1–2s) and retry.
2. **Backoff + jitter.** Base wait = `Retry-After`; add random jitter of ±20% (or
   exponential backoff with full jitter when the header is absent) so multiple workers
   don't retry in lockstep (thundering herd).
3. **Proactive throttling.** Track `X-MinLimit-Remaining` per tenant and pause scheduling
   when it approaches 0 — cheaper than handling 429s. Enforce a per-tenant concurrency
   cap of ≤4 (leave headroom under the 5-call concurrent limit) with a semaphore, and a
   per-tenant token bucket at ~55 calls/min.
4. **Retry budget.** Bounded retries: e.g. max 5 attempts / ~10 minutes per job, then
   the job is re-queued with `next_run_at = now + Retry-After` (for `day` problems:
   reschedule to the next day window — retrying within the day is pointless).
5. **Job scheduling.** A scheduler distributes tenants across time instead of syncing
   all tenants at :00; a tenant hitting its daily limit is paused, others are unaffected
   (limits are per connection).

**Do not retry:** 400 validation errors (fix the payload — Xero returns structured
validation errors, and batch responses embed per-element errors with
`StatusAttributeString: "ERROR"`; requeue only failed elements), 401 after one
refresh+retry (needs reauth), 403 (scope/tenant config), 404 (resource/config), 5xx is
the only status besides 429 that deserves bounded automatic retries.

---

## C5 — Data integrity: duplicate invoice creation

Problem: internal order → create invoice in Xero; the POST times out; the order is
retried. The first attempt may have succeeded server-side.

Prevention, layered:

1. **Deterministic business key.** Set `InvoiceNumber` from the internal order id
   (e.g. `INV-<orderId>`), and put the order id in `Reference`. Xero enforces unique
   invoice numbers per type within an organisation: the retried create fails with a
   validation error instead of creating a duplicate. Treat "invoice number already
   exists" as *success-with-lookup*, not as an error.
2. **Local outbox/state machine.** The order row has `invoice_status`:
   `pending → sent(key) → confirmed(invoiceId)`. A retry only fires for `sent` rows
   whose outcome is unknown, and it begins with a lookup, not a blind re-POST:
3. **Reconcile before re-creating.** On retry (or on a scheduled reconciler):
   `GET /Invoices?where=InvoiceNumber=="INV-<orderId>"` (or `?Statuses=...` +
   Reference match). Found → store the `InvoiceID`, mark `confirmed`, done. Not found →
   the original request truly failed → safe to create. This closes the
   "succeeded but response lost" hole deterministically.
4. **Record Xero-correlation-id** of every create attempt; if a duplicate ever slips
   through (e.g. invoice number uniqueness was bypassed), the reconciler flags two
   invoices sharing one `Reference`/order id, voids the later one, and alerts.

Pseudocode for the retried send:

```
if order.invoice_status == confirmed: return
existing = xero.get_invoices(where=f'InvoiceNumber=="{order.invoice_number}"')
if existing:
    confirm(order, existing[0].InvoiceID)          # response was lost, not the invoice
else:
    resp = xero.create_invoice(number=order.invoice_number, reference=order.id, ...)
    if resp.ok:                       confirm(order, resp.InvoiceID)
    elif resp.is_duplicate_number():  confirm(order, lookup_again().InvoiceID)
    else:                             raise   # validation error -> fix data, not retry
```

---

## C6 — Observability and security

**Logs** (structured, per tenant, sampled on success): sync job start/end, cursor
transitions, page counts, per-endpoint call counts, error class (auth/validation/rate/
server), remediation taken (refresh, requeue, quarantine). Every log line carries:
`correlation_id` (our job/run id), `xero_correlation_id` (from the
`Xero-Correlation-Id` response header — essential for Xero support tickets), `tenant_id`,
`endpoint`, `status`, `attempt`.

**Metrics:** per-tenant API calls/min vs. limit (`X-*-Remaining` as gauges), 429 rate by
`X-Rate-Limit-Problem`, token refresh success/failure, sync lag (now − watermark), page
throughput, duplicate-suppression count, quarantined records.

**Alerts:** refresh-token failure / `invalid_grant` (connection dead — page someone or
notify the customer to reconnect), sustained 429s (scheduling bug), sync lag > threshold,
quarantine queue non-empty, daily-limit utilisation > 80%.

**Never logged:** access tokens, refresh tokens, client secret, authorisation codes,
full `Authorization` headers, and raw payloads containing personal data beyond what's
needed (log ids/hashes, not bank details or contact PII). Redact at the logging
pipeline, not by convention.

**Secret storage & rotation:** client secret in the platform secret manager
(e.g. KMS/Vault/SSM), never in env files committed to the repo or in the database as
plaintext. Token sets stored encrypted at rest (AES-GCM with a data-encryption key per
tenant, envelope-encrypted by KMS), keyed by `tenant_id` so a lookup bug can't cross
tenants. Rotation: Xero rotates the **refresh token on every use** — persist the new one
transactionally with the sync that used it, before the worker can crash and lose it
(the old token is invalid immediately). Client secret rotation is done by adding the new
secret, draining in-flight flows, then revoking the old one. Access is audited; workers
get short-lived, least-privilege credentials to the token store only.
