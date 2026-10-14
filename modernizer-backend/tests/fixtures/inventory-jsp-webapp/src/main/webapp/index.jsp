<%@ page contentType="text/html;charset=UTF-8" %>
<html>
<head><title>Inventory</title></head>
<body>
<h1>Acme Inventory</h1>
<% String user = (String) session.getAttribute("user"); %>
<% if (user == null) { %>
  <p><a href="login.jsp">Sign in</a></p>
<% } else { %>
  <p>Welcome, ${user}.</p>
  <ul>
    <li><a href="products">Products</a></li>
    <li><a href="order.jsp">New order</a></li>
    <li><a href="login?action=logout">Sign out</a></li>
  </ul>
<% } %>
</body>
</html>
