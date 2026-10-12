<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<header class="top">
  <h1>Order Management</h1>
  <nav>
    <a href="<c:url value='/orders'/>">Orders</a>
    <a href="<c:url value='/orders/new'/>">New order</a>
    <a href="<c:url value='/customers'/>">Customers</a>
  </nav>
</header>
<script>var API_BASE = '${apiBase}';</script>
