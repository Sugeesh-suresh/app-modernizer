# JSP / Servlet web tier — what to document

Where to look:
- Views: `*.jsp`, `*.jspx`, `*.jspf`, tag files (`*.tag`, `*.tagx`), `WEB-INF/tags`, TLDs
- Web configuration: `WEB-INF/web.xml`, servlet/filter/listener annotations, Struts/Spring MVC configuration, Tiles/SiteMesh layouts
- Controllers and servlets that forward to or include the views
- Static assets: JavaScript, CSS, images, and client-side libraries under the web root

What to record:
- Every page: path, the URL that renders it, the controller/servlet that forwards to it, includes and layout
- Data each page reads (request/session/application attributes, model objects) and the forms it submits (action URL, method, fields, validation)
- Scriptlets and expression-language logic embedded in pages, and the business rules they apply
- Tag libraries used (JSTL, custom tags) and what the custom tags do
- Navigation flow between pages, session handling, authentication and authorisation checks in the web tier
- Filters and listeners, error pages, character encoding, i18n bundles
- Client-side behaviour: JavaScript functions, AJAX calls and the endpoints they hit
- Tests covering the web tier (servlet tests, Selenium/HtmlUnit, MockMvc) and what they need to run
