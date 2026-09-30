import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProductPage from "./ProductPage";
import type { Product } from "../types";

const product: Product = {
  id: "p1",
  name: "Aurora Merino Hoodie",
  description: "A test hoodie.",
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderLoaded() {
  const user = userEvent.setup();
  render(<ProductPage productId="p1" />);
  await screen.findByRole("heading", { name: "Aurora Merino Hoodie" });
  return user;
}

describe("ProductPage", () => {
  it("resolves the selected variant and updates price, image and stock", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(product));
    const user = await renderLoaded();

    // incomplete selection: no price yet, add-to-cart blocked
    expect(screen.getByTestId("price")).toHaveTextContent(/select options/i);

    // Olive disables the impossible S combination
    await user.click(screen.getByRole("button", { name: "Olive" }));
    expect(screen.getByRole("button", { name: "S" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "M" }));
    expect(screen.getByTestId("price")).toHaveTextContent("$95.00");
    expect(screen.getByTestId("stock-status")).toHaveTextContent(/in stock/i);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/img/hoodie-olive.svg");

    // switching to the out-of-stock White/M SKU flips the state
    await user.click(screen.getByRole("button", { name: "White" }));
    expect(screen.getByTestId("price")).toHaveTextContent("$89.00");
    expect(screen.getByTestId("stock-status")).toHaveTextContent(/out of stock/i);
    expect(screen.getByRole("button", { name: /out of stock/i })).toBeDisabled();
  });

  it("double-clicking add to cart sends exactly one request", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(product));
    const user = await renderLoaded();
    await user.click(screen.getByRole("button", { name: "Black" }));
    await user.click(screen.getByRole("button", { name: "M" }));

    // keep the POST pending so the second click lands mid-flight
    let resolvePost: (r: Response) => void = () => {};
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          resolvePost = resolve;
        }),
    );

    const addButton = screen.getByRole("button", { name: /add to cart/i });
    await user.click(addButton);
    await user.click(addButton); // must be a no-op: button is disabled while adding

    const postCalls = () =>
      fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST");
    expect(postCalls()).toHaveLength(1);

    // the request carries an Idempotency-Key header
    const [, init] = postCalls()[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();

    resolvePost(
      jsonResponse(
        {
          item: { sku_id: "SKU-BLA-M", quantity: 1, unit_price_cents: 8900 },
          stock_remaining: 11,
          cart: { items: [], total_items: 1, total_price_cents: 8900 },
        },
        201,
      ),
    );
    await screen.findByText(/added 1 × SKU-BLA-M/i);
    expect(screen.getByLabelText(/cart contains 1 items/i)).toBeInTheDocument();
  });

  it("shows a retryable error when the product load fails, then recovers", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network down"));
    const user = userEvent.setup();
    render(<ProductPage productId="p1" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't load this product/i);

    // reviewer kills one request; the UI must recover without a page refresh
    fetchMock.mockResolvedValueOnce(jsonResponse(product));
    await user.click(screen.getByRole("button", { name: /retry/i }));
    await screen.findByRole("heading", { name: "Aurora Merino Hoodie" });
  });

  it("surfaces a server-side stock conflict as accessible feedback", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(product));
    const user = await renderLoaded();
    await user.click(screen.getByRole("button", { name: "Black" }));
    await user.click(screen.getByRole("button", { name: "M" }));

    // server now reports less stock than the initial product response
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { error: { code: "INSUFFICIENT_STOCK", message: "Only 0 unit(s) remain." } },
        409,
      ),
    );
    await user.click(screen.getByRole("button", { name: /add to cart/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/only 0 unit/i);
    });
  });

  it("reuses the idempotency key when retrying after a network error", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(product));
    const user = await renderLoaded();
    await user.click(screen.getByRole("button", { name: "Black" }));
    await user.click(screen.getByRole("button", { name: "M" }));

    // first attempt fails at the network layer: the server outcome is unknown
    fetchMock.mockRejectedValueOnce(new TypeError("network down"));
    await user.click(screen.getByRole("button", { name: /add to cart/i }));
    await screen.findByText(/network error/i);

    // retrying the same action must reuse the key so the server can deduplicate
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          item: { sku_id: "SKU-BLA-M", quantity: 1, unit_price_cents: 8900 },
          stock_remaining: 11,
          cart: { items: [], total_items: 1, total_price_cents: 8900 },
        },
        201,
      ),
    );
    await user.click(screen.getByRole("button", { name: /add to cart/i }));
    await screen.findByText(/added 1 × SKU-BLA-M/i);

    const posts = fetchMock.mock.calls.filter(
      ([, init]) => (init as RequestInit)?.method === "POST",
    );
    expect(posts).toHaveLength(2);
    const keyOf = (call: unknown[]) =>
      ((call[1] as RequestInit).headers as Record<string, string>)["Idempotency-Key"];
    expect(keyOf(posts[1])).toBe(keyOf(posts[0]));
  });
});
