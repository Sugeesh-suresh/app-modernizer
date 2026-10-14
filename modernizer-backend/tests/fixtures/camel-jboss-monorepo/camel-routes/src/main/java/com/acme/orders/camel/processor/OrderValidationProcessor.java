package com.acme.orders.camel.processor;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import javax.validation.ConstraintViolation;
import javax.validation.Validation;
import javax.validation.Validator;

import org.apache.camel.Exchange;
import org.apache.camel.Processor;

import com.acme.orders.camel.exception.OrderValidationException;
import com.acme.orders.model.Order;

/** Validates the {@link Order} body with Bean Validation and throws when it is invalid. */
public class OrderValidationProcessor implements Processor {

    private volatile Validator validator;

    @Override
    public void process(Exchange exchange) throws Exception {
        Order order = exchange.getIn().getBody(Order.class);
        if (order == null) {
            throw new OrderValidationException("Message body is not an Order", new ArrayList<String>());
        }
        Set<ConstraintViolation<Order>> violations = validator().validate(order);
        if (!violations.isEmpty()) {
            List<String> messages = new ArrayList<String>();
            for (ConstraintViolation<Order> v : violations) {
                messages.add(v.getPropertyPath() + " " + v.getMessage());
            }
            throw new OrderValidationException("Order " + order.getId() + " is invalid", messages);
        }
    }

    private Validator validator() {
        if (validator == null) {
            validator = Validation.buildDefaultValidatorFactory().getValidator();
        }
        return validator;
    }
}
