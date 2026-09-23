# Legacy JSP/Servlet/Spring MVC Constructs — What to Look For and Why It Matters

This is a discovery checklist, not evidence about the repository in front of you.
Nothing here asserts that a construct is present; use it only to decide what to
go looking for, and record what you actually read.

Describe observed behaviour and dependencies. Do NOT record what a construct
"becomes", where it "belongs", or whether it is presentation or business logic —
that decision belongs to a later skill, and a fact file that pre-empts it hands
the classifier its own guesses back as evidence.

## Scriptlets, declarations and expressions
- `<% ... %>` (scriptlet) — raw Java embedded in markup. Transcribe what it reads, what it calls, and what it writes. Do not characterise it.
- `<%= ... %>` (expression) — a value written straight into the response. Record the expression and what produces the value.
- `<%! ... %>` (declaration) — page-scoped fields and methods, compiled into the generated servlet class. Rare, easy to miss entirely, and frequently holds real logic. Note that declared fields are shared across concurrent requests to that page.
- `<%@ page import/session/errorPage/isErrorPage/contentType/pageEncoding %>` — record these when they affect behaviour (whether a session is created, which page handles thrown exceptions, response encoding).

## Expression Language
- `${ ... }` — record every expression. Note explicit scope references (`pageScope`, `requestScope`, `sessionScope`, `applicationScope`, `param`, `header`, `cookie`, `initParam`, `pageContext`).
- An unqualified `${foo}` resolves across page → request → session → application in that order. Its origin is *not* established by the expression alone — mark it scope-implicit unless a writer site in the source establishes where it came from.
- `#{ ... }` (deferred EL) — appears with JSF or tag files; different evaluation timing, record it separately.
- EL functions (`${my:fn(x)}`) — resolve the function through the `.tld` to its backing Java method and record what that method does.

## JSTL, Spring and custom tags
- Core (`<c:if>`, `<c:choose>`, `<c:forEach>`, `<c:set>`, `<c:out>`, `<c:url>`, `<c:redirect>`, `<c:import>`) — record the condition, the collection, the variable and the scope written to. `<c:set>` with `scope="session"` is a state write and belongs in the state inventory.
- Formatting and i18n (`<fmt:formatDate>`, `<fmt:formatNumber>`, `<fmt:message>`, `<fmt:setBundle>`) — record the pattern/key and the resource bundle it resolves against.
- Spring tags (`<form:form>`, `<form:input>`, `<form:errors>`, `<spring:url>`, `<spring:message>`) — these bind to a command/model object; record the `modelAttribute`/`path` and the backing object, not just the markup.
- Security tags (`<sec:authorize>`, `<sec:authentication>`) — record the expression and what it gates.
- Custom taglibs — read the `.tld` and then the tag handler class. Generic advice does not apply; record what the handler actually does, including anything it writes to scope or to the response.
- Tag files (`.tag`, `.tagx`) — these are views in their own right; record their attributes, their body handling and their own logic.

## Implicit and servlet objects
- `request.getParameter`/`getParameterValues`/`getParts` — input. Record every name read.
- `request.getAttribute`/`setAttribute` — single-request handoff. Record the key, the writer and every reader.
- `session.getAttribute`/`setAttribute`/`removeAttribute`/`invalidate` — multi-request state. Record the key, every writer, every reader, and any observed removal or invalidation. Do not infer a lifetime from the key's name or from one access site.
- `application`/`ServletContext` attributes — process-wide shared state; note concurrency-sensitive writes.
- `response.setHeader`/`addCookie`/`setStatus`/`sendError`/`getWriter`/`getOutputStream` — direct response manipulation from inside a view is easy to miss and changes what the page actually returns.
- `pageContext`, `config`, `out`, `exception` — record when used behaviourally.

## Forms
- `<form>` — record `action`, `method`, `enctype`, `target`, and whether the action is a literal path, an EL expression or assembled in JavaScript.
- Every submit-capable control — `name`, type, default/selected value, `disabled`/`readonly`, hidden fields, file inputs, and named submit buttons (a servlet often branches on which button's name arrived).
- Client-side submission — `onsubmit`, `onclick` handlers, `form.submit()` calls, and any validation that runs before the post.
- Server-side handling — find the corresponding read sites and any validation in the handler, and record both. Record where a validation failure sends the user and what it puts in scope.

## Includes, composition and layout
- `<%@ include file="..." %>` — static, compile-time; the fragment's declarations and scriptlets share the including page's generated class.
- `<jsp:include page="..."/>` with `<jsp:param>` — dynamic, request-time, separate dispatch.
- `<jsp:forward>` — terminates the current page's rendering.
- Tiles, SiteMesh, or a hand-rolled layout convention — record the definition files and how a view name resolves to a composed page.
- Not every `.jsp` is directly addressable. Classify each file's role (addressable view, view target resolved by configuration, included fragment, tag file, error page, layout) or record it as unknown.

## Request routing and cross-cutting server code
- `web.xml`/`web-fragment.xml` — servlet and filter mappings, `<welcome-file-list>`, `<error-page>`, context params, listeners, session config, security constraints. Do not assume `web.xml` exists, and do not assume it is the only mapping source.
- `@WebServlet`/`@WebFilter`/`@WebListener` and programmatic registration via `ServletContainerInitializer`/`WebApplicationInitializer`.
- Spring `DispatcherServlet` — its mapping, its context configuration, component scanning, and the view resolvers that turn a returned view name into a JSP path. A handler's JSP target is usually only establishable by combining the returned name with the resolver's prefix/suffix; record the resolver rules, and mark the target unresolved if they do not determine it.
- `@Controller`/`@RequestMapping` (class and method level), plus method/params/headers/consumes/produces constraints and `@PathVariable`/`@RequestParam`/`@RequestHeader`/`@CookieValue`/`@RequestBody`/`@ModelAttribute`/`@SessionAttributes`.
- Legacy Spring controllers (`SimpleFormController`, `MultiActionController`, `Controller` interface) and XML-defined handler mappings — these predate annotations and are invisible to a scan for `@RequestMapping`.
- Struts/WebWork/XWork actions, JSF managed beans, or a custom front controller — record whichever is actually found rather than assuming Spring.
- Filters, interceptors (`HandlerInterceptor`), listeners, `HandlerExceptionResolver`s and security filter chains — record what each reads, writes, blocks, redirects or wraps, the condition that triggers it, and its ordering when the configuration establishes one.

## Navigation
- `RequestDispatcher.forward(...)` — server-side, URL unchanged in the browser.
- `RequestDispatcher.include(...)` — composes another resource's output into this response.
- `response.sendRedirect(...)` and Spring's `redirect:` / `forward:` view prefixes — record the target and whether it is internal or external.
- `RedirectAttributes`/flash attributes — state that survives exactly one redirect.
- Error-page dispatch and exception-resolver paths are navigation too; record what triggers them and where they land.
- Links, `<meta http-equiv="refresh">`, `window.location` assignments, popups and download responses.
- If a destination is assembled at runtime from a variable or a parameter, record the expression and mark the destination unresolved rather than guessing.

## Client-side behaviour referenced by the views
- Script and stylesheet references, inline `<script>` blocks, and inline event-handler attributes.
- Server values injected into JavaScript (a scriptlet or EL expression written inside a `<script>` block) — record the value, its source scope, and what the script does with it.
- Backbone — models, collections, views, routers and routes, `sync`/custom transports, and the URLs they call.
- YUI — modules loaded, `Y.io` calls and their endpoints, and event bindings.
- Plain XHR/`fetch`/jQuery AJAX — record the endpoint, method, payload shape and the success/error paths.
- Browser-side state — `localStorage`, `sessionStorage`, IndexedDB, cookies written from script, hash/history routes, and JavaScript globals.

## Tests
- Check the test source roots and the build configuration before concluding anything about coverage. Record the framework, the files, what behaviour each test targets, and the fixtures or mocks it depends on.
- JSP markup itself is usually untested; state that as an observation about what you found, not as an assumption.

## What NOT to assume
- Do not assume a 1:1 mapping between JSP pages and future routes or components. Record what exists.
- Do not assume embedded logic is presentation logic because it sits in a `.jsp` file, or that logic in a controller is business logic because it sits in Java.
- Do not assume all state lives in `HttpSession`, or that a session attribute lives for the whole session.
- Do not assume all behaviour is server-side; a legacy app of this era frequently has substantial logic in Backbone, YUI or hand-written scripts.
- Do not assume all redirects are internal navigation.
- Do not report a mapping, a dependency, a lifetime or a test you have not read in a source or configuration file.
