import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addCartItem, ApiError, getProduct, newIdempotencyKey } from "../api/client";
import { clampQuantity, isValueAvailable, resolveSku } from "../domain/variants";
import type { Product, Selection, Sku } from "../types";
import { formatPrice } from "../types";

type LoadState = "loading" | "error" | "ready";
type AddState = "idle" | "adding";

interface Feedback {
  kind: "success" | "error";
  message: string;
}

export default function ProductPage({ productId }: { productId: string }) {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [product, setProduct] = useState<Product | null>(null);
  const [selection, setSelection] = useState<Selection>({});
  const [quantity, setQuantity] = useState(1);
  const [addState, setAddState] = useState<AddState>("idle");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [cartCount, setCartCount] = useState(0);

  // One key per add-to-cart attempt: a retried attempt reuses the key so the
  // server can deduplicate it; a *new* user action mints a fresh key.
  const idempotencyKey = useRef<string>(newIdempotencyKey());

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const p = await getProduct(productId);
      setProduct(p);
      setSelection(Object.fromEntries(p.options.map((d) => [d.name, null])));
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  const sku: Sku | null = useMemo(
    () => (product ? resolveSku(product, selection) : null),
    [product, selection],
  );

  function selectOption(dimension: string, value: string) {
    if (!product) return;
    const next = { ...selection, [dimension]: value };
    setSelection(next);
    setFeedback(null);
    // keep the quantity valid for the newly resolved SKU
    const nextSku = resolveSku(product, next);
    if (nextSku) setQuantity((q) => clampQuantity(q, nextSku.stock) || 1);
  }

  async function handleAddToCart() {
    if (!product || addState === "adding") return; // re-entrancy guard
    if (!sku) {
      setFeedback({ kind: "error", message: "Please choose every option first." });
      return;
    }
    setAddState("adding");
    setFeedback(null);
    try {
      const result = await addCartItem(sku.id, quantity, idempotencyKey.current);
      // reflect the authoritative server state (stock may have moved)
      setProduct({
        ...product,
        skus: product.skus.map((s) =>
          s.id === sku.id ? { ...s, stock: result.stock_remaining } : s,
        ),
      });
      setCartCount(result.cart.total_items);
      setQuantity((q) => clampQuantity(q, result.stock_remaining) || 1);
      setFeedback({
        kind: "success",
        message: `Added ${result.item.quantity} × ${sku.id} to the cart.`,
      });
      // definitive success: the next, distinct action mints a fresh key
      idempotencyKey.current = newIdempotencyKey();
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Something went wrong. Please retry.";
      setFeedback({ kind: "error", message });
      // Only rotate the key on a *definitive* failure (the server responded and
      // decided, i.e. any 4xx). On an unknown-outcome failure — network error
      // (status 0) or 5xx — keep the key so a retry of this same action is
      // deduplicated server-side instead of double-adding.
      const unknownOutcome =
        err instanceof ApiError && (err.status === 0 || err.status >= 500);
      if (!unknownOutcome) {
        idempotencyKey.current = newIdempotencyKey();
      }
    } finally {
      setAddState("idle");
    }
  }

  // ---- render states --------------------------------------------------------

  if (loadState === "loading") {
    return (
      <p role="status" className="state-message">
        Loading product…
      </p>
    );
  }

  if (loadState === "error" || !product) {
    return (
      <div role="alert" className="state-message">
        <p>We couldn't load this product.</p>
        <button type="button" onClick={() => void load()}>
          Retry
        </button>
      </div>
    );
  }

  const outOfStock = sku !== null && sku.stock === 0;
  const canAdd =
    sku !== null && !outOfStock && quantity >= 1 && addState === "idle";

  return (
    <main className="pdp">
      <section className="pdp-media" aria-label="Product images">
        <img
          src={sku?.image ?? product.images[0]}
          alt={`${product.name}${sku ? ` in ${sku.options["Colour"]}` : ""}`}
          width={480}
          height={480}
        />
      </section>

      <section className="pdp-details">
        <header className="pdp-header">
          <h1>{product.name}</h1>
          <span className="cart-badge" aria-label={`Cart contains ${cartCount} items`}>
            Cart: {cartCount}
          </span>
        </header>
        <p>{product.description}</p>
        <p className="price" data-testid="price">
          {sku ? formatPrice(sku.price_cents) : "Select options to see the price"}
        </p>
        <p className="stock" data-testid="stock-status" role="status">
          {sku === null
            ? ""
            : outOfStock
              ? "Out of stock"
              : sku.stock <= 5
                ? `Only ${sku.stock} left`
                : "In stock"}
        </p>

        {product.options.map((dim) => (
          <fieldset key={dim.name} className="option-group">
            <legend>{dim.name}</legend>
            {dim.values.map((value) => {
              const available = isValueAvailable(product, selection, dim.name, value);
              const selected = selection[dim.name] === value;
              return (
                <button
                  key={value}
                  type="button"
                  className={`option-chip${selected ? " selected" : ""}`}
                  aria-pressed={selected}
                  disabled={!available}
                  title={available ? value : `${value} is unavailable for this combination`}
                  onClick={() => selectOption(dim.name, value)}
                >
                  {value}
                </button>
              );
            })}
          </fieldset>
        ))}

        <label className="quantity">
          Quantity
          <input
            type="number"
            min={1}
            max={sku?.stock ?? 1}
            value={quantity}
            disabled={!sku || outOfStock}
            onChange={(e) =>
              setQuantity(clampQuantity(Number(e.target.value) || 1, sku?.stock ?? 1))
            }
          />
        </label>

        <button
          type="button"
          className="add-to-cart"
          disabled={!canAdd}
          aria-busy={addState === "adding"}
          onClick={() => void handleAddToCart()}
        >
          {addState === "adding" ? "Adding…" : outOfStock ? "Out of stock" : "Add to cart"}
        </button>

        {/* aria-live announces success/error feedback to assistive technology */}
        <div
          role={feedback?.kind === "error" ? "alert" : "status"}
          aria-live="polite"
          className={`feedback ${feedback?.kind ?? ""}`}
        >
          {feedback?.message}
        </div>
      </section>
    </main>
  );
}
