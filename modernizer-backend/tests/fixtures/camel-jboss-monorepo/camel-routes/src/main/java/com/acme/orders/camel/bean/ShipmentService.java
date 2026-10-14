package com.acme.orders.camel.bean;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.apache.camel.Body;

import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.model.Shipment;
import com.acme.orders.util.OrderUtil;

/** Creates shipments for accepted orders and keeps them by order id. */
public class ShipmentService {

    private final Map<String, Shipment> shipmentsByOrder = new ConcurrentHashMap<String, Shipment>();

    public Shipment ship(@Body Order order) {
        String carrier = order.isPriority() ? "EXPRESS-AIR" : "GROUND";
        Shipment shipment = new Shipment("SHP-" + order.getId(), order.getId(), carrier,
                OrderUtil.newId("TRK"));
        shipmentsByOrder.put(order.getId(), shipment);
        order.setStatus(OrderStatus.SHIPPED);
        return shipment;
    }

    public Shipment findByOrderId(String orderId) {
        return shipmentsByOrder.get(orderId);
    }

    public int count() {
        return shipmentsByOrder.size();
    }
}
