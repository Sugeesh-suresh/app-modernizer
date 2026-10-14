<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="spring" uri="http://www.springframework.org/tags" %>
<jsp:include page="../layout/header.jsp"/>
<h1><c:out value="${product.name}"/></h1>
<dl>
  <dt><spring:message code="product.sku"/></dt><dd><c:out value="${product.sku}"/></dd>
  <dt><spring:message code="product.price"/></dt><dd><c:out value="${formattedPrice}"/></dd>
  <dt><spring:message code="product.stock"/></dt><dd><c:out value="${product.stock}"/></dd>
</dl>
<jsp:include page="../layout/footer.jsp"/>
