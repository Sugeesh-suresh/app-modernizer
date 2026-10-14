package com.acme.orders.api.web;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.apache.camel.CamelContext;
import org.apache.camel.ProducerTemplate;
import org.apache.camel.Route;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import com.acme.orders.api.repository.OrderRepository;
import com.acme.orders.model.StatusReport;

@RestController
@RequestMapping("/api")
public class RouteController {

    private final CamelContext camelContext;
    private final ProducerTemplate producer;
    private final OrderRepository orders;

    @Autowired
    public RouteController(CamelContext camelContext, ProducerTemplate producer, OrderRepository orders) {
        this.camelContext = camelContext;
        this.producer = producer;
        this.orders = orders;
    }

    /** 9. run the report route once, on demand, and return what it produced */
    @RequestMapping(value = "/routes/report/trigger", method = RequestMethod.POST)
    public StatusReport triggerReport() {
        return producer.requestBody("direct:report", orders.findAll(), StatusReport.class);
    }

    /** 10. health: Camel context and per-route status */
    @RequestMapping(value = "/health", method = RequestMethod.GET)
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<String, Object>();
        boolean started = camelContext.getStatus().isStarted();
        body.put("status", started ? "UP" : "DOWN");
        body.put("camelContext", camelContext.getName());
        body.put("camelVersion", camelContext.getVersion());
        List<Map<String, String>> routes = new ArrayList<Map<String, String>>();
        for (Route r : camelContext.getRoutes()) {
            Map<String, String> entry = new LinkedHashMap<String, String>();
            entry.put("id", r.getId());
            entry.put("status", String.valueOf(camelContext.getRouteStatus(r.getId())));
            routes.add(entry);
        }
        body.put("routes", routes);
        return body;
    }
}
