// API types mirroring the backend contract. Money is integer cents.

export interface Sku {
  id: string;
  price_cents: number;
  stock: number;
  image: string;
  options: Record<string, string>;
}

export interface OptionDimension {
  name: string;
  values: string[];
}

export interface Product {
  id: string;
  name: string;
  description: string;
  images: string[];
  options: OptionDimension[];
  skus: Sku[];
}

export interface CartItem {
  sku_id: string;
  quantity: number;
  unit_price_cents: number;
}

export interface Cart {
  items: CartItem[];
  total_items: number;
  total_price_cents: number;
}

export interface AddToCartResponse {
  item: CartItem;
  stock_remaining: number;
  cart: Cart;
}

export type Selection = Record<string, string | null>;

export function formatPrice(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
