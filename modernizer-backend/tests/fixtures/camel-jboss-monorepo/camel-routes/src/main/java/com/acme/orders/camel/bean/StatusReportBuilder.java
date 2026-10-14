package com.acme.orders.camel.bean;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

import org.apache.camel.Body;

import com.acme.orders.model.Order;
import com.acme.orders.model.OrderStatus;
import com.acme.orders.model.StatusReport;
import com.acme.orders.util.OrderUtil;

public class StatusReportBuilder {

    public StatusReport build(@Body List<Order> orders) {
        StatusReport report = new StatusReport();
        report.setGeneratedAt(new Date());
        for (OrderStatus s : OrderStatus.values()) {
            report.getCountsByStatus().put(s.name(), 0);
        }
        BigDecimal value = BigDecimal.ZERO;
        if (orders != null) {
            report.setTotalOrders(orders.size());
            for (Order o : orders) {
                String key = o.getStatus().name();
                report.getCountsByStatus().put(key, report.getCountsByStatus().get(key) + 1);
                value = value.add(OrderUtil.total(o));
            }
        }
        report.setTotalValue(value);
        return report;
    }
}
