<%@ page contentType="text/html;charset=UTF-8" import="java.util.*,com.acme.inventory.model.Product" %>
<html>
<head><title>Products</title></head>
<body>
<h1>Products</h1>
<form method="get" action="products">
  <input type="text" name="q" value="${q}"/> <input type="submit" value="Search"/>
</form>
<table border="1">
  <tr><th>SKU</th><th>Name</th><th>Price</th><th>Stock</th></tr>
<%
  List<Product> products = (List<Product>) request.getAttribute("products");
  if (products != null) {
    for (Product p : products) {
%>
  <tr>
    <td><%= p.getSku() %></td>
    <td><%= p.getName() %></td>
    <td><%= p.getPrice() %></td>
    <td><%= p.isInStock() ? String.valueOf(p.getStock()) : "Out of stock" %></td>
  </tr>
<%
    }
  }
%>
</table>
<p>Page ${page} of ${pages}</p>
<% Integer pg = (Integer) request.getAttribute("page"); Integer pgs = (Integer) request.getAttribute("pages"); %>
<% if (pg != null && pg > 1) { %><a href="products?page=<%= pg - 1 %>">Prev</a><% } %>
<% if (pg != null && pgs != null && pg < pgs) { %><a href="products?page=<%= pg + 1 %>">Next</a><% } %>
</body>
</html>
