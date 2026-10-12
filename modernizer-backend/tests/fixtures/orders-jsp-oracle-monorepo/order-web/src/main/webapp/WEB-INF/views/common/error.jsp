<%@ page contentType="text/html;charset=UTF-8" isErrorPage="true" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<html><head><title>Error</title><link rel="stylesheet" href="<c:url value='/static/css/orders.css'/>"></head>
<body>
<%@ include file="header.jsp" %>
<p class="error"><c:out value="${message}" default="The page you asked for does not exist."/></p>
</body></html>
