<%@ page contentType="text/html;charset=UTF-8" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="fmt" uri="http://java.sun.com/jsp/jstl/fmt" %>
<html>
<head>
  <title>Orders</title>
  <link rel="stylesheet" href="<c:url value='/static/css/orders.css'/>">
  <script src="<c:url value='/static/js/jquery-1.12.4.min.js'/>"></script>
  <script src="<c:url value='/static/js/orders.js'/>"></script>
</head>
<body>
<%@ include file="../common/header.jsp" %>
<section>
  <form id="filter">
    <label for="status">Status</label>
    <select id="status" name="status">
      <option value="">All</option>
      <c:forEach var="s" items="${['NEW','APPROVED','SHIPPED','CANCELLED']}">
        <option value="${s}" <c:if test="${s == status}">selected</c:if>>${s}</option>
      </c:forEach>
    </select>
    <button type="submit">Filter</button>
  </form>

  <table id="orders">
    <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th>Total</th><th>Created</th><th></th></tr></thead>
    <tbody>
    <%-- First page rendered on the server (order-web -> order-services); later pages come over AJAX. --%>
    <c:forEach var="o" items="${recent}">
      <tr data-id="${o.id}">
        <td><a href="<c:url value='/orders/${o.id}'/>"><c:out value="${o.orderNumber}"/></a></td>
        <td><c:out value="${o.customerName}"/></td>
        <td class="status"><c:out value="${o.status}"/></td>
        <td><fmt:formatNumber value="${o.total}" type="currency"/></td>
        <td><c:out value="${o.createdAt}"/></td>
        <td><c:if test="${o.status == 'NEW'}"><button class="approve">Approve</button></c:if></td>
      </tr>
    </c:forEach>
    </tbody>
  </table>
  <button id="more" data-page="1">Load more</button>
</section>
</body>
</html>
