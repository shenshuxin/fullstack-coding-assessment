// Pure variant-resolution logic, separated from UI so it is trivially testable.

import type { Product, Selection, Sku } from "../types";

/** True when every option dimension has a selected value. */
export function isComplete(product: Product, selection: Selection): boolean {
  return product.options.every((dim) => selection[dim.name] != null);
}

/**
 * The SKU matching the current selection, or null when the selection is
 * incomplete or names an unavailable combination (no such SKU exists).
 */
export function resolveSku(product: Product, selection: Selection): Sku | null {
  if (!isComplete(product, selection)) return null;
  return (
    product.skus.find((sku) =>
      product.options.every((dim) => sku.options[dim.name] === selection[dim.name]),
    ) ?? null
  );
}

/**
 * Whether picking `value` for `dimension` can still lead to a real SKU,
 * given the other dimensions' current selections. Used to disable
 * impossible/unavailable combinations.
 */
export function isValueAvailable(
  product: Product,
  selection: Selection,
  dimension: string,
  value: string,
): boolean {
  return product.skus.some((sku) =>
    product.options.every((dim) => {
      const wanted = dim.name === dimension ? value : selection[dim.name];
      return wanted == null || sku.options[dim.name] === wanted;
    }),
  );
}

/** Clamp a requested quantity into [1, stock]; 0 when there is no stock. */
export function clampQuantity(quantity: number, stock: number): number {
  if (stock <= 0) return 0;
  return Math.min(Math.max(1, quantity), stock);
}
