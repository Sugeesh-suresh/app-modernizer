<%@ page contentType="text/html;charset=UTF-8" isErrorPage="true" %>
<html>
<head><title>Error</title></head>
<body>
<h1>Something went wrong</h1>
<p>${error != null ? error : "Unexpected error"}</p>
<a href="index.jsp">Home</a>
</body>
</html>
