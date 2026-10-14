<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="spring" uri="http://www.springframework.org/tags" %>
<%@ taglib prefix="form" uri="http://www.springframework.org/tags/form" %>
<jsp:include page="../layout/header.jsp"/>
<h1><spring:message code="product.new.title"/></h1>
<form:form method="post" action="${pageContext.request.contextPath}/products" modelAttribute="product">
  <p><spring:message code="product.sku"/>: <form:input path="sku"/> <form:errors path="sku" cssClass="error"/></p>
  <p><spring:message code="product.name"/>: <form:input path="name"/> <form:errors path="name" cssClass="error"/></p>
  <p><spring:message code="product.price"/>: <form:input path="price"/> <form:errors path="price" cssClass="error"/></p>
  <p><spring:message code="product.stock"/>: <form:input path="stock"/> <form:errors path="stock" cssClass="error"/></p>
  <input type="submit" value="<spring:message code='product.save'/>"/>
</form:form>
<jsp:include page="../layout/footer.jsp"/>
