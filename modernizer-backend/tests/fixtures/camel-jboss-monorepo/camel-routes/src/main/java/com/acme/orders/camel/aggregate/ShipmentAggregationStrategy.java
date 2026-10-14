package com.acme.orders.camel.aggregate;

import java.util.ArrayList;
import java.util.List;

import org.apache.camel.Exchange;
import org.apache.camel.processor.aggregate.AggregationStrategy;

/** Collects the shipment notifications of one carrier into a single List body. */
public class ShipmentAggregationStrategy implements AggregationStrategy {

    @Override
    @SuppressWarnings("unchecked")
    public Exchange aggregate(Exchange oldExchange, Exchange newExchange) {
        Object incoming = newExchange.getIn().getBody();
        if (oldExchange == null) {
            List<Object> list = new ArrayList<Object>();
            list.add(incoming);
            newExchange.getIn().setBody(list);
            return newExchange;
        }
        List<Object> list = oldExchange.getIn().getBody(List.class);
        list.add(incoming);
        return oldExchange;
    }
}
