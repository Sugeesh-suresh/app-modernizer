<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<%@ taglib prefix="c" uri="http://java.sun.com/jsp/jstl/core" %>
<!DOCTYPE html>
<html>
<head>
  <title>Claims</title>
  <link rel="stylesheet" href="/static/css/claims.css"/>
  <script src="/static/js/jquery-3.6.0.min.js"></script>
  <script src="/static/js/claims-list.js"></script>
</head>
<body>
<%@ include file="../common/header.jsp" %>
<h1>Claims</h1>
<form id="filterForm" action="/claims" method="get">
  <label for="statusFilter">Status</label>
  <select id="statusFilter" name="status">
    <option value="">All</option>
    <option value="OPEN">Open</option>
    <option value="APPROVED">Approved</option>
    <option value="REJECTED">Rejected</option>
  </select>
  <button type="submit">Filter</button>
</form>
<input type="text" id="policySearch" placeholder="Policy number"/>
<button type="button" id="searchBtn">Search</button>
<table id="claimsTable">
  <thead><tr><th>Claim</th><th>Policy</th><th>Amount</th><th>Status</th><th></th></tr></thead>
  <tbody id="claimsBody"></tbody>
</table>
<c:if test="${not empty status}">
  <p class="filter-note">Showing ${status} claims</p>
</c:if>
<button type="button" id="exportBtn" onclick="exportClaims()">Export CSV</button>
<script>
  function exportClaims() {
    window.location.href = '/claims-api/api/claims/export?status=' + $('#statusFilter').val();
  }
</script>
</body>
</html>
