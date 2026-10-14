package com.acme.orders.api.web;

import java.util.List;

import javax.validation.Valid;

import org.apache.camel.ProducerTemplate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

import com.acme.orders.api.error.NotFoundException;
import com.acme.orders.api.repository.OrderRepository;
import com.acme.orders.camel.bean.ShipmentService;
import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.model.Shipment;
import com.acme.orders.util.OrderUtil;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private static final Logger LOG = LoggerFactory.getLogger(OrderController.class);

    private final OrderRepository orders;
    private final ProducerTemplate producer;
    private final ShipmentService shipments;

    @Autowired
    public OrderController(OrderRepository orders, ProducerTemplate producer, ShipmentService shipments) {
        this.orders = orders;
        this.producer = producer;
        this.shipments = shipments;
    }

    /** 1. list orders */
    @RequestMapping(method = RequestMethod.GET)
    public List<Order> list() {
        return orders.findAll();
    }

    /** 2. one order */
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    public Order get(@PathVariable("id") String id) {
        return require(id);
    }

    /** 3. create: validated, stored, then handed to the Camel intake route. */
    @RequestMapping(method = RequestMethod.POST)
    public ResponseEntity<Order> create(@Valid @RequestBody Order order) {
        order.setId(OrderUtil.newId("ORD"));
        order.setStatus(OrderStatus.RECEIVED);
        orders.save(order);
        LOG.info("Sending order {} into direct:orderIn", order.getId());
        producer.sendBody("direct:orderIn", order);
        return new ResponseEntity<Order>(order, HttpStatus.ACCEPTED);
    }

    /** 4. replace an order that has not shipped yet */
    @RequestMapping(value = "/{id}", method = RequestMethod.PUT)
    public Order update(@PathVariable("id") String id, @Valid @RequestBody Order changes) {
        Order existing = require(id);
        existing.setCustomerId(changes.getCustomerId());
        existing.setLines(changes.getLines());
        existing.setPriority(changes.isPriority());
        existing.setNotes(changes.getNotes());
        return orders.save(existing);
    }

    /** 5. delete */
    @RequestMapping(value = "/{id}", method = RequestMethod.DELETE)
    public ResponseEntity<Void> delete(@PathVariable("id") String id) {
        if (orders.delete(id) == null) {
            throw new NotFoundException("Order", id);
        }
        return new ResponseEntity<Void>(HttpStatus.NO_CONTENT);
    }

    /** 6. shipment created by the fulfilment route */
    @RequestMapping(value = "/{id}/shipment", method = RequestMethod.GET)
    public Shipment shipment(@PathVariable("id") String id) {
        require(id);
        Shipment s = shipments.findByOrderId(id);
        if (s == null) {
            throw new NotFoundException("Shipment for order", id);
        }
        return s;
    }

    private Order require(String id) {
        Order o = orders.findById(id);
        if (o == null) {
            throw new NotFoundException("Order", id);
        }
        return o;
    }
}
