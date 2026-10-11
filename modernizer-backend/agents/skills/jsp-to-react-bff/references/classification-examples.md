# Worked Classification Examples

## Example 1 — mixed-concern scriptlet (must be split)

```jsp
<%
  User user = (User) session.getAttribute("user");
  double total = 0;
  for (CartItem item : cart.getItems()) {
      total += item.getPrice() * item.getQuantity();
  }
  double discounted = user.isPremium() ? total * 0.9 : total;
%>
Total: <%= String.format("$%.2f", discounted) %>
```

Split into three rows, not one:
| Logic Unit | Classification | Reasoning |
|---|---|---|
| Reading `user` from session | Backend | Rule 3 — server-owned session identity |
| Summing cart item totals | Backend | Rule 1 — this is the authoritative order total, must not be trusted from a client-recomputed value |
| Premium discount calculation | Backend | Rule 2 — pricing/business rule, client must not decide its own discount |
| Formatting the total as currency for display | Frontend | Rule 4 — pure presentation once the BFF has returned the (already-discounted) total |

The React component receives `{ total: 45.00 }` (already discounted) from the BFF and only formats it for display — it never recomputes the discount.

## Example 2 — client-only interaction state JSP couldn't really express

```jsp
<c:if test="${showAdvancedOptions}">
  <!-- advanced fields -->
</c:if>
<input type="checkbox" onclick="document.forms[0].submit()" name="showAdvanced" />
```

This is a classic JSP-era workaround: a full page reload just to toggle visibility of a form section, because JSP had no client-side state model. Classification: **Frontend**, Rule 5 — `showAdvancedOptions` becomes a local `useState` boolean in the React component, toggled with no network round-trip at all. Call this out explicitly in the plan as a **behavioural improvement**, not just a like-for-like port — the migration removes an unnecessary full-page reload.

## Example 3 — validation, correctly classified as Both

```java
// In the backing servlet
if (email == null || !email.matches("^[^@]+@[^@]+\\.[^@]+$")) {
    request.setAttribute("error", "Invalid email");
    request.getRequestDispatcher("/register.jsp").forward(request, response);
    return;
}
```

- **Backend** (authoritative): the BFF's registration endpoint must perform this exact check and reject the request with a 400 and the same error semantics if it fails — a client could bypass any frontend validation entirely.
- **Frontend** (UX only): the React form should apply the same regex on blur/submit to give immediate feedback before hitting the network, but must never be the only place this check exists.

Never classify a validation rule as frontend-only just because the *symptom* (an inline error message) was rendered in the JSP page — the *rule itself* nearly always has a backend home too.
