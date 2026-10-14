<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="spring" uri="http://www.springframework.org/tags" %>
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title><spring:message code="app.title"/></title>
  <link rel="stylesheet" href="<c:url value='/static/css/shop.css'/>"/>
</head>
<body>
<div id="nav">
  <a href="<c:url value='/products'/>"><spring:message code="nav.products"/></a> |
  <a href="<c:url value='/products/new'/>"><spring:message code="nav.new"/></a> |
  <a href="?lang=en"><spring:message code="lang.en"/></a> / <a href="?lang=fr"><spring:message code="lang.fr"/></a>
</div>
<c:if test="${not empty message}">
  <p class="flash"><spring:message code="${message}"/></p>
</c:if>
