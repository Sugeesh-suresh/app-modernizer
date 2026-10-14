# inventory-jsp-webapp (test fixture)

Small JSP + servlet WAR (single Maven module, Java 8 source/target) used as the target repository
for the test-coverage-uplift pipeline. Servlets, filter and listener use `javax.servlet` (Servlet 3.1,
`provided`); there is no Spring and no JSTL. JSPs are plain scriptlet/EL and are not precompiled or unit-tested.

Build/test: `mvn -o -B -q test` (all dependencies and plugins are in a warm `~/.m2`; drop `-o` otherwise).

Surefire is configured with a literal `<argLine>-Xmx256m -Dfile.encoding=UTF-8</argLine>` (no `@{argLine}`).
This is deliberate: it overrides the property JaCoCo's `prepare-agent` sets, so the agent is not attached.
There is no JaCoCo in the pom.

## Existing tests (3 classes, all passing)
- `PricingServiceTest`, `InputValidatorTest`, `ProductListServletTest`

## Covered by design
- `service.PricingService`, `util.InputValidator`, `web.ProductListServlet` (mostly)

## Uncovered by design (zero or near-zero)
- `service.InventoryService`, `service.InsufficientStockException`
- `web.OrderServlet`, `web.LoginServlet`, `web.AuthFilter`, `web.AppContextListener`
- `util.CsvExporter`, `util.DateRange`
- `dao.JdbcProductDao` (`DaoException` is only constructed in one test)
- model: `OrderStatus` (zero), `Product` (constructor/getters only); `Order`/`OrderLine` only touched by one PricingServiceTest case (subtotal path)
