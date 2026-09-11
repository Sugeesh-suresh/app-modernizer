# JSP → Thymeleaf (required for an executable JAR)

An executable JAR's embedded Tomcat cannot serve JSPs, so every JSP view becomes a Thymeleaf template. Do not fall back to an executable WAR to keep JSPs alive — the final artifact is always a JAR.

## Mechanics

- `src/main/webapp/WEB-INF/views/<name>.jsp` → `src/main/resources/templates/<name>.html`. Keep the same view name so controllers that return `"<name>"` need no change.
- Add `spring-boot-starter-thymeleaf`. Remove the `InternalResourceViewResolver` bean, any `spring.mvc.view.prefix` / `suffix` properties, JSTL and `tomcat-embed-jasper`.
- Root element: `<html xmlns:th="http://www.thymeleaf.org">`. Templates must be well-formed HTML5, so close every tag.
- Static assets the JSP referenced (`/css/…`, `/js/…`, images) move to `src/main/resources/static/`.
- Delete each JSP once its template exists, then the empty `WEB-INF/views` directory.

## Translation table

| JSP / JSTL | Thymeleaf |
|---|---|
| `<%@ page … %>`, `<%@ taglib … %>` | Delete |
| `${expr}` written straight into the HTML (unescaped in JSP) | `th:text="${expr}"` (escaped). Use `th:utext` only where the JSP deliberately emitted HTML |
| `<c:out value="${x}"/>` | `<span th:text="${x}">sample</span>` |
| `<c:forEach items="${list}" var="o">` | `th:each="o : ${list}"` on the element being repeated (e.g. the `<tr>`) |
| `<c:if test="${cond}">` | `th:if="${cond}"` |
| `<c:choose>` / `<c:when>` / `<c:otherwise>` | A `th:if` / `th:unless` pair, or `th:switch` / `th:case` |
| `${empty list}` | `${#lists.isEmpty(list)}`; for strings `${#strings.isEmpty(s)}`; otherwise `${x == null}` |
| `<c:url value="/path"/>` | `th:href="@{/path}"` / `th:src="@{/path}"` — the context path is added automatically |
| `<c:url value="/api/items/${o.id}"/>` | `th:href="@{/api/items/{id}(id=${o.id})}"` |
| `<fmt:formatNumber value="${n}" maxFractionDigits="1"/>` | `${#numbers.formatDecimal(n, 1, 1)}` — match the original fraction digits as closely as possible |
| `<fmt:formatDate value="${d}" pattern="yyyy-MM-dd HH:mm"/>` | `${#dates.format(d, 'yyyy-MM-dd HH:mm')}` for `java.util.Date`; `${#temporals.format(t, '…')}` for `java.time` |
| `<jsp:include page="header.jsp"/>` | `th:replace="~{fragments/header :: header}"` |
| Scriptlets `<% … %>` | Move the logic into the controller or model; never port Java code into a template |

## Nulls

JSP EL renders a null as an empty string. When a formatted value can be null, guard it so the output stays blank rather than failing:

```html
<td th:text="${o.windSpeedKph != null} ? ${#numbers.formatDecimal(o.windSpeedKph, 1, 1)} : ''"></td>
```

## Verify

Every model attribute the JSP read (`observations`, `error`, …) must still be set by the controller under the same name. Every link must resolve to the same URL as before, including the context path.
