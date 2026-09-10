# Legacy JSP/Servlet Constructs — What to Look For and Why It Matters

## Scriptlets and expressions
- `<% ... %>` (scriptlet) and `<%= ... %>` (expression) — raw Java embedded in markup. This is almost always either (a) presentation formatting that belongs in a React component, or (b) business logic that was only in the view layer because JSP made no distinction, and belongs in the BFF/service layer. The classifier decides which; your job is just to transcribe what each one does.
- `<%! ... %>` (declaration) — page-scoped fields/methods; rare, but if present, note it — it often hides real business logic (e.g. a helper method) that a naive migration would drop entirely.

## JSTL and custom tags
- `<c:if>`/`<c:choose>` — conditional rendering. Usually becomes conditional JSX rendering, but if the condition depends on business rules (not just "is this field present"), the rule itself may belong server-side.
- `<c:forEach>` — iteration over a collection put in request/session scope by a servlet. Usually becomes a `.map()` over data fetched from a BFF endpoint.
- `<fmt:formatDate>`/`<fmt:formatNumber>` — presentation formatting; almost always a frontend concern (or a BFF response-shaping concern if the format is a business rule, e.g. a specific currency locale mandated by policy).
- Custom taglibs (`.tld`-declared) — read the tag handler class; it's doing something specific enough that generic advice doesn't apply. Record exactly what it does.

## Implicit objects
- `request.getParameter(...)` — form/query input. Becomes a React form field bound to component state, submitted to a BFF endpoint.
- `request.getAttribute(...)` / `setAttribute(...)` — single-request-scoped data handoff from servlet to JSP. Becomes a BFF API response field.
- `session.getAttribute(...)` / `setAttribute(...)` — multi-request user state (login identity, shopping cart, wizard-flow progress). This is the highest-risk category — flag every single one, because the BFF must now own this state (server-side session, or a client-visible token) instead of the container's default `HttpSession` cookie tying it to a JSP-rendered page.
- `application.getAttribute(...)` — app-wide shared state (rare, often a cache or a singleton config holder). Usually becomes a BFF-side singleton/bean, never client state.

## Forms
- `<form action="..." method="post">` plus `<input name="...">` fields — this is a page-load/full-postback interaction model. Record the exact field names and the action URL; these become a React form component's fields and the BFF endpoint it POSTs to.
- Look for server-side validation of these fields in the backing servlet (`if (name == null || name.isEmpty())`-style checks) — this validation logic must be preserved, most naturally in the BFF (server-side, authoritative) and often duplicated client-side for UX (immediate feedback), but the source of truth is the BFF version.

## Includes
- `<%@ include file="..." %>` (static, compile-time) vs `<jsp:include page="..." />` (dynamic, request-time) — both indicate a reusable fragment (a header, footer, nav bar, or a repeated widget). These become shared React components.

## Navigation
- `RequestDispatcher.forward(...)` — server-side forward, URL doesn't change in the browser. Becomes either a client-side route change (if it's pure navigation) or a re-render driven by a new BFF response (if it's showing a result of the POST).
- `response.sendRedirect(...)` — client-visible redirect, URL does change. Becomes a client-side route change (`navigate(...)` in React Router or equivalent).

## What NOT to assume
- Do not assume a 1:1 mapping between JSP pages and React pages/components — a JSP page assembled from three includes might become one React page composed of three components, or might be split differently if the includes' actual responsibilities don't map cleanly. Record what exists; let the classifier and planner decide the target shape.
- Do not assume all embedded logic is "presentation" just because it's in a JSP file — plenty of legacy JSP apps have real business logic (pricing calculations, authorization checks) embedded directly in scriptlets purely because that was the path of least resistance in the original codebase.
