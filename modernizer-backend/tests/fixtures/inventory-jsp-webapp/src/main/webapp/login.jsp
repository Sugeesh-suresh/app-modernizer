<%@ page contentType="text/html;charset=UTF-8" %>
<html>
<head><title>Sign in</title></head>
<body>
<h1>Sign in</h1>
<% if (request.getAttribute("error") != null) { %>
  <p style="color:red">${error}</p>
<% } %>
<form method="post" action="login">
  <label>Username <input type="text" name="username"/></label><br/>
  <label>Password <input type="password" name="password"/></label><br/>
  <input type="submit" value="Sign in"/>
</form>
</body>
</html>
