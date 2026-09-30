"""API tests: success flow, validation, idempotency, and the stock race.

Run:  python -m pytest tests/ -q   (from app/backend/)

Async endpoints are exercised through httpx + ASGITransport; each test drives
its coroutine with asyncio.run so no pytest plugin is required. The race test
uses asyncio.gather, so the two requests genuinely interleave on one loop.
"""

import asyncio
import uuid

import httpx

from app.main import create_app
from app.store import build_seed_store


def run(coro):
    return asyncio.run(coro)


def make_client(store=None):
    app = create_app(store or build_seed_store())
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def key() -> str:
    return str(uuid.uuid4())


# --- catalogue ---------------------------------------------------------------

def test_get_product_returns_options_and_skus():
    async def scenario():
        async with make_client() as client:
            return await client.get("/api/products/p1")

    resp = run(scenario())
    assert resp.status_code == 200
    body = resp.json()
    assert [o["name"] for o in body["options"]] == ["Colour", "Size"]
    assert len(body["skus"]) == 8                      # 3x3 minus one unavailable combo
    assert not any(s["options"] == {"Colour": "Olive", "Size": "S"} for s in body["skus"])
    assert any(s["stock"] == 0 for s in body["skus"])  # one out-of-stock SKU


def test_get_unknown_product_is_structured_404():
    async def scenario():
        async with make_client() as client:
            return await client.get("/api/products/nope")

    resp = run(scenario())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


# --- add to cart: success + validation ----------------------------------------

def test_add_to_cart_success_updates_cart_and_stock():
    async def scenario():
        async with make_client() as client:
            resp = await client.post(
                "/api/cart/items",
                json={"sku_id": "SKU-BLA-M", "quantity": 2},
                headers={"Idempotency-Key": key()},
            )
            cart = await client.get("/api/cart")
            return resp, cart

    resp, cart = run(scenario())
    assert resp.status_code == 201
    body = resp.json()
    assert body["item"]["unit_price_cents"] == 8900  # server-side price
    assert body["stock_remaining"] == 10
    assert body["cart"]["total_items"] == 2
    assert cart.json()["total_items"] == 2
    assert cart.json()["total_price_cents"] == 2 * 8900


def test_validation_rejects_bad_input():
    async def scenario():
        async with make_client() as client:
            zero_qty = await client.post(
                "/api/cart/items",
                json={"sku_id": "SKU-BLA-M", "quantity": 0},
                headers={"Idempotency-Key": key()},
            )
            unknown_sku = await client.post(
                "/api/cart/items",
                json={"sku_id": "SKU-GHOST", "quantity": 1},
                headers={"Idempotency-Key": key()},
            )
            no_key = await client.post(
                "/api/cart/items", json={"sku_id": "SKU-BLA-M", "quantity": 1}
            )
            return zero_qty, unknown_sku, no_key

    zero_qty, unknown_sku, no_key = run(scenario())
    assert zero_qty.status_code == 400
    assert zero_qty.json()["error"]["code"] == "INVALID_INPUT"
    assert unknown_sku.status_code == 404
    assert unknown_sku.json()["error"]["code"] == "SKU_NOT_FOUND"
    assert no_key.status_code == 400
    assert no_key.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_insufficient_stock_is_409_and_changes_nothing():
    async def scenario():
        async with make_client() as client:
            resp = await client.post(
                "/api/cart/items",
                json={"sku_id": "SKU-WHI-M", "quantity": 1},  # seeded with stock 0
                headers={"Idempotency-Key": key()},
            )
            cart = await client.get("/api/cart")
            return resp, cart

    resp, cart = run(scenario())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert cart.json()["total_items"] == 0


# --- idempotency ---------------------------------------------------------------

def test_same_idempotency_key_does_not_add_twice():
    async def scenario():
        async with make_client() as client:
            k = key()
            payload = {"sku_id": "SKU-BLA-M", "quantity": 1}
            first = await client.post("/api/cart/items", json=payload,
                                      headers={"Idempotency-Key": k})
            replay = await client.post("/api/cart/items", json=payload,
                                       headers={"Idempotency-Key": k})
            cart = await client.get("/api/cart")
            return first, replay, cart

    first, replay, cart = run(scenario())
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert cart.json()["total_items"] == 1  # not 2


def test_reused_key_with_different_payload_is_409():
    async def scenario():
        async with make_client() as client:
            k = key()
            await client.post("/api/cart/items",
                              json={"sku_id": "SKU-BLA-M", "quantity": 1},
                              headers={"Idempotency-Key": k})
            return await client.post("/api/cart/items",
                                     json={"sku_id": "SKU-BLA-M", "quantity": 3},
                                     headers={"Idempotency-Key": k})

    resp = run(scenario())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISMATCH"


# --- the stock race --------------------------------------------------------------

def test_concurrent_requests_cannot_oversell_final_unit():
    """Two requests race for the last unit: exactly one must win."""
    store = build_seed_store()
    store.skus["SKU-BLA-M"].stock = 1  # single final unit

    async def race():
        async with make_client(store) as client:
            return await asyncio.gather(
                client.post("/api/cart/items",
                            json={"sku_id": "SKU-BLA-M", "quantity": 1},
                            headers={"Idempotency-Key": key()}),
                client.post("/api/cart/items",
                            json={"sku_id": "SKU-BLA-M", "quantity": 1},
                            headers={"Idempotency-Key": key()}),
            )

    r1, r2 = run(race())
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 409]
    assert store.skus["SKU-BLA-M"].stock == 0
    assert store.cart().total_items == 1
