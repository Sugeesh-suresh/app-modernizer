# Thymeleaf 2 → 3 (existing Thymeleaf templates)
<!-- applies-to: thymeleaf, th:, layout:decorator, templates/ -->

_For applications that already render with Thymeleaf. JSP views are converted with `jsp-to-thymeleaf.md`; this
file covers templates written for Thymeleaf 2.1 (Spring Boot 1.5) that must run on Thymeleaf 3.0 (Spring Boot
2.x) and 3.1 (Spring Boot 3.x / 4.x)._

A template error is never a compile error: `mvn package` passes with every page broken. Verify the pages by
rendering them (a `@WebMvcTest` or `@SpringBootTest` + MockMvc test per controller that asserts the view renders
and shows a known value) — the plan's verification for a Thymeleaf application must say so.

## Versions

| Spring Boot | Thymeleaf | Layout dialect (`nz.net.ultraq.thymeleaf:thymeleaf-layout-dialect`) |
|---|---|---|
| 1.5 | 2.1 | 1.x / 2.x (supports `layout:decorator`) |
| 2.x | 3.0 | 2.x (deprecates `layout:decorator`) |
| 3.x / 4.x | 3.1 | 3.x+ (`layout:decorator` removed) |

Let Spring Boot manage the Thymeleaf version; take the layout dialect version from the approved-versions list,
or the one Spring Boot manages.

## Required changes

1. **Template mode.** `HTML5` and `LEGACYHTML5` no longer exist: remove `spring.thymeleaf.mode=HTML5` (the default
   `HTML` is right) and any `TemplateMode.HTML5` / `setTemplateMode("HTML5")`. Thymeleaf 3 parses HTML5 leniently
   itself — drop `net.sourceforge.nekohtml` if it was only there for LEGACYHTML5.
2. **Layout dialect.** `layout:decorator="layout"` → `layout:decorate="~{layout}"`. `layout:fragment`,
   `layout:title-pattern` are unchanged. Declare the dependency explicitly from Boot 3 on if it was implicit.
3. **Fragment expressions.** Wrap fragment references: `th:replace="fragments/header :: header"` →
   `th:replace="~{fragments/header :: header}"` (the unwrapped form is deprecated in 3.1 and logs a warning per
   render). Parameterised fragments keep their syntax: `~{fragments/footer :: productCard(${p})}`.
4. **`th:include`** is deprecated since 3.0. `th:include` inserted only the fragment's *content* into the host;
   - `th:replace` replaces the host with the fragment element (use it when the host is just a placeholder);
   - `th:insert` keeps the host and puts the whole fragment element inside it.
   Pick the one that keeps the rendered markup the same.
5. **Inclusion runs before iteration.** Attribute precedence is fragment inclusion (`th:insert`/`th:replace`/
   `th:include`) → `th:each` → `th:if`/`th:unless` → … On ONE element, `th:each` + `th:replace` evaluates the
   fragment before the loop variable exists. Move the loop to a wrapper:
   `<th:block th:each="p : ${products}"><div th:replace="~{fragments/footer :: productCard(${p})}"></div></th:block>`.
   (This was already broken on Thymeleaf 2 — check whether the page ever rendered before preserving its output.)
6. **Removed expression objects (3.1).** `#request`, `#response`, `#session`, `#servletContext`,
   `#httpServletRequest`, `#httpSession` are gone. Put what the template needs in the model (or a
   `@ControllerAdvice` `@ModelAttribute`). `${param.x}` and `${session.x}` attribute access still work.
7. **Restricted expressions (3.1).** Event-handler attributes (`th:onclick` …) accept only numbers and booleans
   from expressions — pass values through `data-*` attributes (`th:data-id="${p.id}"`) and read them in JS. Review
   any `T(...)` static call or object instantiation in an expression; 3.1 restricts them.
8. **JavaScript inlining** (`th:inline="javascript"` with `/*[[...]]*/` natural templates) is unchanged; the
   `/*<![CDATA[*/ … /*]]>*/` wrapper can stay. Values are now JSON-serialised (a String keeps its quotes).
9. **Spring Security dialect.** `thymeleaf-extras-springsecurity4/5` → `thymeleaf-extras-springsecurity6`
   (namespace `http://www.thymeleaf.org/extras/spring-security`, attributes unchanged).
10. **Bean references** (`${@cart.count}`) still work; a session-scoped proxied bean must still be resolvable when
    the template renders (a render test catches it).

## Manifest

Every template using any construct above is a manifest row of the stage that moves Spring Boot (the 2.x stage for
items 1–4 in an incremental run, the Boot 3/4 stage for items 6–9), plus `application.properties`/`.yml` for the
template mode and the POM for the layout dialect and security extras.
