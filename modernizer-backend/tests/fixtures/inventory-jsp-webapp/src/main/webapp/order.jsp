<%@ page contentType="text/html;charset=UTF-8" %>
<html>
<head><title>New order</title></head>
<body>
<h1>New order</h1>
<% if (request.getAttribute("error") != null) { %>
  <p style="color:red">${error}</p>
<% } %>
<% if ("1".equals(request.getParameter("ok"))) { %>
  <p>Order placed. Total: ${sessionScope.lastOrderTotal}</p>
<% } %>
<form method="post" action="order">
  <label>Customer <input type="text" name="customer"/></label><br/>
  <label>Region
    <select name="region"><option>US</option><option>EU</option><option>UK</option><option>JP</option></select>
  </label><br/>
  <label>Product id <input type="text" name="productId"/></label><br/>
  <label>Quantity <input type="text" name="quantity" value="1"/></label><br/>
  <input type="submit" value="Place order"/>
</form>
</body>
</html>
