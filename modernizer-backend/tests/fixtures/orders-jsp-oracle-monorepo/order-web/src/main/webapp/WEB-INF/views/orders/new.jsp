<%@ page contentType="text/html;charset=UTF-8" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<html>
<head>
  <title>New order</title>
  <link rel="stylesheet" href="<c:url value='/static/css/orders.css'/>">
  <script src="<c:url value='/static/js/jquery-1.12.4.min.js'/>"></script>
  <script src="<c:url value='/static/js/new-order.js'/>"></script>
</head>
<body>
<%@ include file="../common/header.jsp" %>
<h2>New order</h2>
<form id="order-form">
  <label for="customer">Customer</label>
  <input id="customer" autocomplete="off" placeholder="Start typing a name">
  <input type="hidden" id="customerId" name="customerId">
  <ul id="customer-suggestions"></ul>

  <table id="lines">
    <thead><tr><th>SKU</th><th>Qty</th><th>Unit price</th><th></th></tr></thead>
    <tbody>
      <tr><td><input name="sku" required></td><td><input name="quantity" type="number" min="1" value="1"></td>
          <td><input name="unitPrice" type="number" step="0.01" min="0"></td><td></td></tr>
    </tbody>
  </table>
  <button type="button" id="add-line">Add line</button>
  <label for="notes">Notes</label>
  <textarea id="notes" name="notes" maxlength="4000"></textarea>
  <p>Total: <span id="total">0.00</span> <span id="approval-hint" hidden>— needs manager approval (over 10,000)</span></p>
  <button type="submit">Place order</button>
  <p id="message"></p>
</form>
</body>
</html>
