import { describe, expect, it } from "vitest";
import { clampQuantity, isValueAvailable, resolveSku } from "./variants";
import type { Product } from "../types";

// mirrors the backend seed data: Olive/S is the unavailable combination,
// White/M is the out-of-stock SKU
const product: Product = {
  id: "p1",
  name: "Aurora Merino Hoodie",
  description: "test",
  images: ["/img/hoodie-black.svg"],
  options: [
    { name: "Colour", values: ["Black", "White", "Olive"] },
    { name: "Size", values: ["S", "M", "L"] },
  ],
  skus: [
    { id: "SKU-BLA-S", price_cents: 8900, stock: 12, image: "/img/hoodie-black.svg", options: { Colour: "Black", Size: "S" } },
    { id: "SKU-BLA-M", price_cents: 8900, stock: 12, image: "/img/hoodie-black.svg", options: { Colour: "Black", Size: "M" } },
    { id: "SKU-BLA-L", price_cents: 8900, stock: 12, image: "/img/hoodie-black.svg", options: { Colour: "Black", Size: "L" } },
    { id: "SKU-WHI-S", price_cents: 8900, stock: 12, image: "/img/hoodie-white.svg", options: { Colour: "White", Size: "S" } },
    { id: "SKU-WHI-M", price_cents: 8900, stock: 0, image: "/img/hoodie-white.svg", options: { Colour: "White", Size: "M" } },
    { id: "SKU-WHI-L", price_cents: 8900, stock: 12, image: "/img/hoodie-white.svg", options: { Colour: "White", Size: "L" } },
    { id: "SKU-OLI-M", price_cents: 9500, stock: 12, image: "/img/hoodie-olive.svg", options: { Colour: "Olive", Size: "M" } },
    { id: "SKU-OLI-L", price_cents: 9500, stock: 12, image: "/img/hoodie-olive.svg", options: { Colour: "Olive", Size: "L" } },
  ],
};

describe("resolveSku", () => {
  it("returns null while the selection is incomplete", () => {
    expect(resolveSku(product, { Colour: "Black", Size: null })).toBeNull();
  });

  it("resolves a complete selection to the matching SKU", () => {
    const sku = resolveSku(product, { Colour: "Olive", Size: "L" });
    expect(sku?.id).toBe("SKU-OLI-L");
    expect(sku?.price_cents).toBe(9500);
  });

  it("returns null for an unavailable combination (Olive/S)", () => {
    expect(resolveSku(product, { Colour: "Olive", Size: "S" })).toBeNull();
  });
});

describe("isValueAvailable", () => {
  it("disables Size=S once Olive is selected", () => {
    const selection = { Colour: "Olive", Size: null };
    expect(isValueAvailable(product, selection, "Size", "S")).toBe(false);
    expect(isValueAvailable(product, selection, "Size", "M")).toBe(true);
  });

  it("keeps every size available for Black", () => {
    const selection = { Colour: "Black", Size: null };
    for (const size of ["S", "M", "L"]) {
      expect(isValueAvailable(product, selection, "Size", size)).toBe(true);
    }
  });

  it("out-of-stock SKUs are still selectable combinations (shown as out of stock)", () => {
    const selection = { Colour: "White", Size: null };
    expect(isValueAvailable(product, selection, "Size", "M")).toBe(true);
  });
});

describe("clampQuantity", () => {
  it("bounds quantity into [1, stock]", () => {
    expect(clampQuantity(0, 5)).toBe(1);
    expect(clampQuantity(3, 5)).toBe(3);
    expect(clampQuantity(99, 5)).toBe(5);
    expect(clampQuantity(2, 0)).toBe(0);
  });
});
