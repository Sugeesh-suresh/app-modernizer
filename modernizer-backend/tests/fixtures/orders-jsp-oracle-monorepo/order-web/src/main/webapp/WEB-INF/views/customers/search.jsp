<%@ page contentType="text/html;charset=UTF-8" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<html>
<head>
  <title>Customers</title>
  <link rel="stylesheet" href="<c:url value='/static/css/orders.css'/>">
</head>
<body>
<%@ include file="../common/header.jsp" %>
<h2>Customers</h2>
<input id="q" placeholder="Name starts with">
<table id="customers"><thead><tr><th>Name</th><th>Email</th><th>Segment</th><th>Credit limit</th></tr></thead><tbody></tbody></table>
<script>
  // Plain XMLHttpRequest (this page predates jQuery being added to the project).
  document.getElementById('q').addEventListener('input', function () {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', API_BASE + '/api/customers?q=' + encodeURIComponent(this.value));
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.onload = function () {
      if (xhr.status !== 200) { return; }
      var rows = JSON.parse(xhr.responseText).map(function (c) {
        return '<tr><td>' + c.name + '</td><td>' + (c.email || '') + '</td><td>' + c.segment + '</td><td>' +
               (c.creditLimit == null ? '' : c.creditLimit) + '</td></tr>';
      });
      document.querySelector('#customers tbody').innerHTML = rows.join('');
    };
    xhr.send();
  });
</script>
</body>
</html>
