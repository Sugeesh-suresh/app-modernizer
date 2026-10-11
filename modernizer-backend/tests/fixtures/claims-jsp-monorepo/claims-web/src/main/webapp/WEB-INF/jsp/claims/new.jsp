<%@ page contentType="text/html;charset=UTF-8" language="java" %>
<!DOCTYPE html>
<html>
<head><title>File a claim</title></head>
<body>
<%@ include file="../common/header.jsp" %>
<h1>File a claim</h1>
<form id="claimForm" action="/claims" method="post">
  <label for="policyNumber">Policy number</label>
  <input type="text" id="policyNumber" name="policyNumber" required maxlength="20" pattern="POL-[0-9]{6}"/>
  <label for="description">What happened?</label>
  <textarea id="description" name="description" required maxlength="2000"></textarea>
  <label for="amount">Amount claimed</label>
  <input type="number" id="amount" name="amount" min="1" max="100000" step="0.01" required/>
  <button type="submit">Submit claim</button>
</form>
</body>
</html>
