<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="fmt" uri="http://java.sun.com/jsp/jstl/fmt" %>
<%@ taglib prefix="spring" uri="http://www.springframework.org/tags" %>
<jsp:include page="../layout/header.jsp"/>
<h1><spring:message code="product.list.title"/></h1>
<form method="get" action="<c:url value='/products'/>">
  <input type="text" name="q" value="<c:out value='${q}'/>"/>
  <input type="submit" value="<spring:message code='product.search'/>"/>
</form>
<c:choose>
  <c:when test="${empty products}"><p><spring:message code="product.none"/></p></c:when>
  <c:otherwise>
    <table>
      <tr>
        <th><spring:message code="product.sku"/></th>
        <th><spring:message code="product.name"/></th>
        <th><spring:message code="product.price"/></th>
        <th><spring:message code="product.stock"/></th>
      </tr>
      <c:forEach var="p" items="${products}">
        <tr>
          <td><c:out value="${p.sku}"/></td>
          <td><a href="<c:url value='/products/${p.id}'/>"><c:out value="${p.name}"/></a></td>
          <td><fmt:formatNumber value="${p.price}" type="currency"/></td>
          <td>
            <c:out value="${p.stock}"/>
            <c:if test="${p.stock lt 5}"><em><spring:message code="product.low"/></em></c:if>
          </td>
        </tr>
      </c:forEach>
    </table>
  </c:otherwise>
</c:choose>
<c:if test="${page > 0}">
  <a href="<c:url value='/products'><c:param name='q' value='${q}'/><c:param name='page' value='${page - 1}'/></c:url>"><spring:message code="product.prev"/></a>
</c:if>
<c:if test="${page + 1 < pages}">
  <a href="<c:url value='/products'><c:param name='q' value='${q}'/><c:param name='page' value='${page + 1}'/></c:url>"><spring:message code="product.next"/></a>
</c:if>
<jsp:include page="../layout/footer.jsp"/>
