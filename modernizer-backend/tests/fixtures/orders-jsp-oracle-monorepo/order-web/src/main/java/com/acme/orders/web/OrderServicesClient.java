package com.acme.orders.web;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.apache.log4j.Logger;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

/** Server-side HTTP calls from the web tier to order-services (used to render pages before any AJAX). */
@Component
public class OrderServicesClient {
    private static final Logger LOG = Logger.getLogger(OrderServicesClient.class);

    private final RestTemplate rest = new RestTemplate();
    private final String baseUrl;

    public OrderServicesClient(@Value("${order.services.url}") String baseUrl) {
        this.baseUrl = baseUrl;
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> order(long id) {
        try {
            return rest.getForObject(baseUrl + "/api/orders/{id}", Map.class, id);
        } catch (RestClientException e) {
            LOG.warn("order-services unavailable for order " + id + ": " + e.getMessage());
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> recentOrders(String status) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("X-Order-User", "order-web");
            ResponseEntity<List> response = rest.exchange(baseUrl + "/api/orders?status={s}&size=10",
                    HttpMethod.GET, new HttpEntity<Void>(headers), List.class, status == null ? "" : status);
            return response.getBody();
        } catch (RestClientException e) {
            LOG.warn("order-services unavailable: " + e.getMessage());
            return Collections.emptyList();
        }
    }
}
