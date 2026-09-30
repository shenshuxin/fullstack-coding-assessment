// Thin typed API layer. UI components never call fetch directly.

import type { AddToCartResponse, Cart, Product } from "../types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, init);
  } catch {
    // network-level failure: no status, unknown server-side outcome
    throw new ApiError(0, "NETWORK_ERROR", "Network error. Please try again.");
  }
  if (!resp.ok) {
    let code = "UNKNOWN_ERROR";
    let message = `Request failed with status ${resp.status}.`;
    try {
      const body = (await resp.json()) as {
        error?: { code?: string; message?: string };
      };
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      // non-JSON error body: keep the generic message
    }
    throw new ApiError(resp.status, code, message);
  }
  return (await resp.json()) as T;
}

export function getProduct(productId: string): Promise<Product> {
  return request<Product>(`/api/products/${encodeURIComponent(productId)}`);
}

export function getCart(): Promise<Cart> {
  return request<Cart>("/api/cart");
}

export function addCartItem(
  skuId: string,
  quantity: number,
  idempotencyKey: string,
): Promise<AddToCartResponse> {
  return request<AddToCartResponse>("/api/cart/items", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ sku_id: skuId, quantity }),
  });
}

export function newIdempotencyKey(): string {
  // crypto.randomUUID is available in all modern browsers and jsdom
  return crypto.randomUUID();
}
