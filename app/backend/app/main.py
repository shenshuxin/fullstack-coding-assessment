"""FastAPI application for the Variant PDP.

Endpoints:
    GET  /api/products/{id}   product + options + SKUs
    POST /api/cart/items      add a SKU (Idempotency-Key header required)
    GET  /api/cart            current cart and totals

Error contract: every non-2xx response has body
    {"error": {"code": "...", "message": "...", "details": {...}?}}

Run:  uvicorn app.main:app --reload --port 8000   (from app/backend/)
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import AddCartItemRequest, Cart, Product
from .store import Store, StoredResponse, build_seed_store

logger = logging.getLogger("variant_pdp")


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="Variant PDP API")
    app.state.store = store or build_seed_store()

    # The Vite dev server runs on :5173; CORS is dev-only convenience.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    def get_store(request: Request) -> Store:
        return request.app.state.store

    # -- error helpers ---------------------------------------------------------

    def error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": message, "details": details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(400, "INVALID_INPUT", "Request failed validation.",
                     {"issues": exc.errors()})

    @app.exception_handler(Exception)
    async def unexpected_handler(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the client; record the full trace for ops.
        logger.exception("Unhandled error: %s", exc)
        return error(500, "INTERNAL_ERROR", "An unexpected error occurred.")

    # -- endpoints ---------------------------------------------------------------

    @app.get("/api/products/{product_id}", response_model=Product)
    async def get_product(product_id: str, store: Store = Depends(get_store)):
        product = store.get_product(product_id)
        if product is None:
            return error(404, "PRODUCT_NOT_FOUND", f"Unknown product '{product_id}'.")
        return product

    @app.post("/api/cart/items", status_code=201)
    async def add_cart_item(
        payload: AddCartItemRequest,
        store: Store = Depends(get_store),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        if not idempotency_key or not idempotency_key.strip():
            return error(400, "MISSING_IDEMPOTENCY_KEY",
                         "The Idempotency-Key header is required.")
        idempotency_key = idempotency_key.strip()

        # The whole idempotency check + stock check + mutation is one critical
        # section: a concurrent request for the same key or the same final unit
        # of stock must observe a committed state, never an intermediate one.
        async with store.lock:
            payload_hash = Store.hash_payload(payload.model_dump())
            seen = store.idempotency.get(idempotency_key)
            if seen is not None:
                if seen.payload_hash != payload_hash:
                    return error(409, "IDEMPOTENCY_KEY_MISMATCH",
                                 "This Idempotency-Key was already used with a different payload.")
                return JSONResponse(status_code=seen.status_code, content=seen.body)

            sku = store.get_sku(payload.sku_id)
            if sku is None:
                response = error(404, "SKU_NOT_FOUND", f"Unknown SKU '{payload.sku_id}'.")
            elif payload.quantity > sku.stock:
                response = error(409, "INSUFFICIENT_STOCK",
                                 f"Only {sku.stock} unit(s) of '{payload.sku_id}' remain.",
                                 {"available": sku.stock})
            else:
                # price is taken from the server-side SKU, never from the client
                sku.stock -= payload.quantity
                store.cart_items[sku.id] = store.cart_items.get(sku.id, 0) + payload.quantity
                item = {
                    "sku_id": sku.id,
                    "quantity": payload.quantity,
                    "unit_price_cents": sku.price_cents,
                }
                response = JSONResponse(
                    status_code=201,
                    content={
                        "item": item,
                        "stock_remaining": sku.stock,
                        "cart": store.cart().model_dump(),
                    },
                )

            # Business outcomes (including rejections) are recorded so a replay
            # of the same key returns an identical response without side effects.
            store.idempotency[idempotency_key] = StoredResponse(
                payload_hash=payload_hash,
                status_code=response.status_code,
                body=json.loads(response.body),
            )
            return response

    @app.get("/api/cart", response_model=Cart)
    async def get_cart(store: Store = Depends(get_store)) -> Cart:
        return store.cart()

    return app


app = create_app()
