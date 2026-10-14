package com.acme.orders.camel.routes;

import org.apache.camel.LoggingLevel;
import org.apache.camel.builder.RouteBuilder;

/**
 * timer:report fires periodically and reports on every order the intake route accepted.
 * direct:report can also be called on demand (used by POST /api/routes/report/trigger).
 */
public class ReportRoute extends RouteBuilder {

    @Override
    public void configure() {
        from("timer:report?period={{report.period}}&delay={{report.delay}}").routeId("report-timer")
            .beanRef("orderRegistry", "all")
            .to("direct:report");

        from("direct:report").routeId("report")
            .beanRef("statusReportBuilder", "build")
            .log(LoggingLevel.INFO, "report: ${body.totalOrders} order(s) ${body.countsByStatus}");
    }
}
