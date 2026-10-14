# Servlets, filters and listeners
<!-- applies-to: servlet, httpservlet, jsp, filter -->

Check the namespace in the sources: `javax.servlet.*` (Java EE / Tomcat 9) or `jakarta.servlet.*` (Tomcat 10+). Import the same one the class under test uses. Mock with Mockito; use Spring's `MockHttpServletRequest` / `MockHttpServletResponse` ONLY if `spring-test` is in the test stack.

## Servlet with Mockito mocks

```java
@Test
public void forwardsToListPageWithOrders() throws Exception {
    HttpServletRequest req = mock(HttpServletRequest.class);
    HttpServletResponse resp = mock(HttpServletResponse.class);
    RequestDispatcher rd = mock(RequestDispatcher.class);
    when(req.getParameter("customer")).thenReturn("42");
    when(req.getRequestDispatcher("/WEB-INF/orders.jsp")).thenReturn(rd);

    servlet.doGet(req, resp);            // doGet is protected: test in the same package, or call service(req, resp)

    verify(req).setAttribute(eq("orders"), any(List.class));
    verify(rd).forward(req, resp);
}
```

`doGet`/`doPost` are `protected`: put the test in the same package (usual layout), or call `service(req, resp)` which needs `getMethod()` stubbed: `when(req.getMethod()).thenReturn("GET")`.

## Writing the response body

```java
StringWriter body = new StringWriter();
when(resp.getWriter()).thenReturn(new PrintWriter(body));
servlet.doGet(req, resp);
verify(resp).setContentType("application/json");
assertEquals("{\"status\":\"ok\"}", body.toString().trim());
```

Call `writer.flush()` before reading if the servlet does not (a `PrintWriter` over `StringWriter` buffers nothing, but a wrapped `BufferedWriter` does). For binary output stub `getOutputStream()` with a `ServletOutputStream` over a `ByteArrayOutputStream` (anonymous subclass; on Servlet 3.1+ also implement `isReady` / `setWriteListener`).

## What to assert, per outcome

| The code | Assert |
|---|---|
| `forward` | `verify(rd).forward(req, resp)` and the path passed to `getRequestDispatcher`; attributes set before it |
| `sendRedirect` | `verify(resp).sendRedirect("/login")` (exact URL; with `encodeRedirectURL` stub it) |
| `sendError` | `verify(resp).sendError(404)` or `(403, "msg")` |
| `setStatus` | `verify(resp).setStatus(201)` |
| session use | stub `req.getSession()` / `getSession(false)` → mock `HttpSession`; `verify(session).setAttribute("user", u)`, `verify(session).invalidate()` |
| cookies / headers | `verify(resp).addCookie(captor.capture())` then assert name, path, maxAge, httpOnly; `verify(resp).setHeader(..)` |
| request attributes | `verify(req).setAttribute(name, value)` or an `ArgumentCaptor` for the value |

Each branch gets its own test: missing parameter, invalid number, not logged in, empty result, exception from the service (assert the error status/redirect, not just "no exception").

## Filters

```java
FilterChain chain = mock(FilterChain.class);
filter.doFilter(req, resp, chain);
verify(chain).doFilter(req, resp);            // passes through
// blocked case:
verify(chain, never()).doFilter(any(), any());
verify(resp).sendError(401);
```

`init(FilterConfig)`: mock `FilterConfig` and stub `getInitParameter`. Test both the configured and the default value.

## Listeners and init

`ServletContextListener.contextInitialized(new ServletContextEvent(ctx))` with a mock `ServletContext`; assert `verify(ctx).setAttribute(..)` or the started component. `HttpSessionListener`: `new HttpSessionEvent(session)`.

## Spring MockHttpServletRequest (only with spring-test)

```java
MockHttpServletRequest req = new MockHttpServletRequest("POST", "/orders");
req.setParameter("sku", "A1");
MockHttpServletResponse resp = new MockHttpServletResponse();
servlet.service(req, resp);
assertEquals(302, resp.getStatus());
assertEquals("/orders/done", resp.getRedirectedUrl());
```

## JSP-backed code

JSP files are not instrumented and are out of scope. Test what runs before the JSP: the servlet/controller that fills request attributes and forwards, form beans, custom tag handler classes (`doStartTag` returns `EVAL_BODY_INCLUDE` / `SKIP_BODY`; mock `PageContext` and `JspWriter`), EL functions (static methods). For a controller, assert the attributes handed to the view and the view name or forward path — not the page's markup.
