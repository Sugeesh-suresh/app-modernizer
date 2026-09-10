# React Frontend Generation Patterns

## package.json skeleton

```json
{
  "name": "frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.0.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0"
  }
}
```

## Typed API client matching the BFF contract exactly

```typescript
// src/api/cart.ts
export interface CartItemDto {
  productId: string;
  name: string;
  quantity: number;
  unitPrice: number;
}
export interface CartResponse {
  items: CartItemDto[];
  total: number;
}
export interface AddItemRequest {
  productId: string;
  quantity: number;
}
export interface FieldError { field: string; message: string; }
export interface ApiErrorResponse { code: string; fieldErrors: FieldError[]; }

const BASE = "/api/cart";

export async function getCart(): Promise<CartResponse> {
  const res = await fetch(BASE, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to load cart");
  return res.json();
}

export async function addItem(request: AddItemRequest): Promise<CartResponse | ApiErrorResponse> {
  const res = await fetch(`${BASE}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include", // carries the session cookie -- no manual token handling
    body: JSON.stringify(request),
  });
  return res.json(); // caller checks res.ok / the shape to distinguish success from ApiErrorResponse
}
```

## Page component: single-page interaction replacing a full-reload form postback

```tsx
// src/pages/CartPage.tsx
import { useEffect, useState } from "react";
import { getCart, addItem, type CartResponse, type FieldError } from "../api/cart";

export function CartPage() {
  const [cart, setCart] = useState<CartResponse | null>(null);
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([]);

  useEffect(() => {
    getCart().then(setCart);
  }, []);

  const handleAdd = async () => {
    // Client-side mirror of the backend's authoritative validation (rule "Both") --
    // immediate feedback only, the real check still happens server-side below.
    if (quantity < 1) {
      setFieldErrors([{ field: "quantity", message: "Quantity must be at least 1" }]);
      return;
    }
    const result = await addItem({ productId, quantity });
    if ("fieldErrors" in result) {
      setFieldErrors(result.fieldErrors); // backend's authoritative validation result
    } else {
      setFieldErrors([]);
      setCart(result); // no page reload -- just re-render with the updated cart
    }
  };

  if (!cart) return <p>Loading…</p>;

  return (
    <div>
      <ul>
        {cart.items.map((item) => (
          <li key={item.productId}>{item.name} × {item.quantity} — ${item.unitPrice}</li>
        ))}
      </ul>
      <p>Total: ${cart.total}</p>
      <input value={productId} onChange={(e) => setProductId(e.target.value)} placeholder="Product ID" />
      <input type="number" value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
      {fieldErrors.map((fe) => <p key={fe.field} className="error">{fe.field}: {fe.message}</p>)}
      <button onClick={handleAdd}>Add to Cart</button>
    </div>
  );
}
```

## Client-side-only state that JSP had no real equivalent for

```tsx
// A tab/section toggle that used to be a full page reload via a hidden form field --
// now genuinely local, no network round-trip at all.
const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
```

## Routing, mirroring the legacy navigation map

```tsx
// src/App.tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { CartPage } from "./pages/CartPage";
import { CheckoutPage } from "./pages/CheckoutPage";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/cart" element={<CartPage />} />
        <Route path="/checkout" element={<CheckoutPage />} />
      </Routes>
    </BrowserRouter>
  );
}
```
A legacy `RequestDispatcher.forward("/checkout.jsp")` after a successful cart update becomes a `navigate("/checkout")` call (or, if the same page just needs updated data rather than a real navigation, simply re-rendering with the new API response — don't add a route change where the legacy forward was really just "show the result of this action on the same page").
