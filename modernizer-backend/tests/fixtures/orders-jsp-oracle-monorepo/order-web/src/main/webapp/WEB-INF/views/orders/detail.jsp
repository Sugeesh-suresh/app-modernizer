<%@ page contentType="text/html;charset=UTF-8" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<%@ taglib prefix="fmt" uri="http://java.sun.com/jsp/jstl/fmt" %>
<html>
<head>
  <title>Order <c:out value="${order.orderNumber}"/></title>
  <link rel="stylesheet" href="<c:url value='/static/css/orders.css'/>">
  <script src="<c:url value='/static/js/jquery-1.12.4.min.js'/>"></script>
</head>
<body>
<%@ include file="../common/header.jsp" %>
<h2>Order <c:out value="${order.orderNumber}"/></h2>
<dl>
  <dt>Customer</dt><dd><c:out value="${order.customerName}"/></dd>
  <dt>Status</dt><dd id="status"><c:out value="${order.status}"/></dd>
  <dt>Total</dt><dd><fmt:formatNumber value="${order.total}" type="currency"/></dd>
  <dt>Notes</dt><dd><c:out value="${order.notes}"/></dd>
</dl>
<table class="lines">
  <thead><tr><th>SKU</th><th>Qty</th><th>Unit price</th></tr></thead>
  <tbody>
  <c:forEach var="l" items="${order.lines}">
    <tr><td><c:out value="${l.sku}"/></td><td>${l.quantity}</td><td><fmt:formatNumber value="${l.unitPrice}" type="currency"/></td></tr>
  </c:forEach>
  </tbody>
</table>
<c:if test="${order.status != 'SHIPPED' && order.status != 'CANCELLED'}">
  <button id="cancel">Cancel order</button>
</c:if>
<p id="message"></p>
<script>
  // Cancel goes straight to order-services; the page only updates the status cell.
  $('#cancel').on('click', function () {
    if (!confirm('Cancel this order?')) { return; }
    $.ajax({
      url: API_BASE + '/api/orders/${order.id}/cancel',
      type: 'POST',
      headers: { 'X-Order-User': 'order-web' },
      dataType: 'json'
    }).done(function (res) {
      $('#status').text(res.status);
      $('#cancel').remove();
    }).fail(function (xhr) {
      var body = xhr.responseJSON || {};
      $('#message').text(body.error || 'Could not cancel the order.');
    });
  });
</script>
</body>
</html>
