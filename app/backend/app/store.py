"""In-memory store with seed data, concurrency control and idempotency.

Design decisions:
- Reservation model: adding to the cart decrements SKU stock immediately.
  This is what makes "oversell" meaningful for a cart API — two concurrent
  requests for the final unit cannot both succeed because the check and the
  decrement happen inside one lock.
- A single asyncio.Lock serialises every cart mutation. The store is
  per-process (documented limitation); the API surface is storage-agnostic so
  the same lock can later be replaced by an atomic SQL statement such as
  `UPDATE sku SET stock = stock - :q WHERE id = :id AND stock >= :q`
  (checking rowcount) without changing endpoint code.
- Idempotency-Key handling: the first execution's (payload hash, status,
  body) is stored under the key. A replay with the same payload returns the
  stored response unchanged; a replay with a *different* payload is a client
  bug and gets 409 IDEMPOTENCY_KEY_MISMATCH.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field

from .models import Cart, CartItem, OptionDimension, Product, Sku


@dataclass
class StoredResponse:
    payload_hash: str
    status_code: int
    body: dict


@dataclass
class Store:
    products: dict[str, Product] = field(default_factory=dict)
    skus: dict[str, Sku] = field(default_factory=dict)
    cart_items: dict[str, int] = field(default_factory=dict)  # sku_id -> qty
    idempotency: dict[str, StoredResponse] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -- catalogue -----------------------------------------------------------

    def get_product(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def get_sku(self, sku_id: str) -> Sku | None:
        return self.skus.get(sku_id)

    # -- cart -----------------------------------------------------------------

    def cart(self) -> Cart:
        items = [
            CartItem(
                sku_id=sku_id,
                quantity=qty,
                unit_price_cents=self.skus[sku_id].price_cents,
            )
            for sku_id, qty in sorted(self.cart_items.items())
        ]
        return Cart(
            items=items,
            total_items=sum(i.quantity for i in items),
            total_price_cents=sum(i.quantity * i.unit_price_cents for i in items),
        )

    # -- idempotency ----------------------------------------------------------

    @staticmethod
    def hash_payload(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()


def build_seed_store() -> Store:
    """One product, two option dimensions, 8 SKUs.

    Colour x Size is 3 x 3 = 9 combinations; Olive/S is intentionally absent
    (unavailable combination) and White/M is seeded with stock 0, satisfying
    the >= 6 SKUs + one unavailable combo + one out-of-stock SKU requirements.
    """
    colours = ["Black", "White", "Olive"]
    sizes = ["S", "M", "L"]
    prices = {"Black": 8900, "White": 8900, "Olive": 9500}
    unavailable = {("Olive", "S")}
    out_of_stock = {("White", "M")}

    skus: list[Sku] = []
    for colour in colours:
        for size in sizes:
            if (colour, size) in unavailable:
                continue
            code = f"{colour[:3].upper()}-{size}"
            skus.append(
                Sku(
                    id=f"SKU-{code}",
                    price_cents=prices[colour],
                    stock=0 if (colour, size) in out_of_stock else 12,
                    image=f"/img/hoodie-{colour.lower()}.svg",
                    options={"Colour": colour, "Size": size},
                )
            )

    product = Product(
        id="p1",
        name="Aurora Merino Hoodie",
        description=(
            "A mid-weight hoodie knitted from traceable merino wool. "
            "Pick a colour and size; some combinations are unavailable."
        ),
        images=["/img/hoodie-black.svg", "/img/hoodie-white.svg", "/img/hoodie-olive.svg"],
        options=[
            OptionDimension(name="Colour", values=colours),
            OptionDimension(name="Size", values=sizes),
        ],
        skus=skus,
    )
    return Store(products={product.id: product}, skus={s.id: s for s in skus})
