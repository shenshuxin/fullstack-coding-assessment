"""Domain and API models for the Variant PDP backend.

Money is handled in integer cents everywhere to avoid float rounding issues.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- domain -----------------------------------------------------------------

class Sku(BaseModel):
    id: str
    price_cents: int
    stock: int
    image: str
    options: dict[str, str]  # e.g. {"Colour": "Black", "Size": "M"}


class OptionDimension(BaseModel):
    name: str
    values: list[str]


class Product(BaseModel):
    id: str
    name: str
    description: str
    images: list[str]
    options: list[OptionDimension]
    skus: list[Sku]


class CartItem(BaseModel):
    sku_id: str
    quantity: int
    unit_price_cents: int


class Cart(BaseModel):
    items: list[CartItem]
    total_items: int
    total_price_cents: int


# --- requests / responses ----------------------------------------------------

class AddCartItemRequest(BaseModel):
    sku_id: str = Field(min_length=1, max_length=64)
    # bounded like a real product: 1..99 per request
    quantity: int = Field(ge=1, le=99)


class AddCartItemResponse(BaseModel):
    item: CartItem
    stock_remaining: int
    cart: Cart


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
