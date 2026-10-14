package com.acme.orders.camel.bean;

import java.util.HashMap;
import java.util.Map;

import org.apache.camel.Body;

import com.acme.orders.model.OrderLine;

/** Adds the catalog description to an order line (invoked once per split line). */
public class LineEnricher {

    private final Map<String, String> catalog = new HashMap<String, String>();

    public LineEnricher() {
        catalog.put("SKU-1", "Widget, standard");
        catalog.put("SKU-2", "Widget, large");
        catalog.put("SKU-3", "Gadget");
    }

    public OrderLine enrich(@Body OrderLine line) {
        String description = catalog.get(line.getSku());
        line.setDescription(description != null ? description : "Unlisted item " + line.getSku());
        return line;
    }
}
