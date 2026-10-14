<%@ page contentType="text/html;charset=UTF-8" language="java" isErrorPage="true" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="spring" uri="http://www.springframework.org/tags" %>
<jsp:include page="layout/header.jsp"/>
<h1><spring:message code="error.title"/></h1>
<p><c:out value="${errorMessage}"/></p>
<jsp:include page="layout/footer.jsp"/>
