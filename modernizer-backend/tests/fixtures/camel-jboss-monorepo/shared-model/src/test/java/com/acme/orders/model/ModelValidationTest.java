package com.acme.orders.model;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.math.BigDecimal;
import java.util.Set;

import javax.validation.ConstraintViolation;
import javax.validation.Validation;
import javax.validation.Validator;

import org.junit.BeforeClass;
import org.junit.Test;

import com.acme.orders.util.OrderUtil;

public class ModelValidationTest {

    private static Validator validator;

    @BeforeClass
    public static void setUpValidator() {
        validator = Validation.buildDefaultValidatorFactory().getValidator();
    }

    private Order validOrder() {
        Order o = new Order();
        o.setCustomerId("C-100");
        o.getLines().add(new OrderLine("SKU-1", 2, new BigDecimal("9.99")));
        return o;
    }

    @Test
    public void validOrderHasNoViolations() {
        assertTrue(validator.validate(validOrder()).isEmpty());
    }

    @Test
    public void blankCustomerIdIsRejected() {
        Order o = validOrder();
        o.setCustomerId("  ");
        Set<ConstraintViolation<Order>> v = validator.validate(o);
        assertEquals(1, v.size());
        assertEquals("customerId", v.iterator().next().getPropertyPath().toString());
    }

    @Test
    public void orderWithoutLinesIsRejected() {
        Order o = validOrder();
        o.getLines().clear();
        assertEquals(1, validator.validate(o).size());
    }

    @Test
    public void invalidLineIsReportedWithIndexedPath() {
        Order o = validOrder();
        o.getLines().get(0).setQuantity(0);
        Set<ConstraintViolation<Order>> v = validator.validate(o);
        assertEquals(1, v.size());
        assertEquals("lines[0].quantity", v.iterator().next().getPropertyPath().toString());
    }

    @Test
    public void customerEmailMustBeWellFormed() {
        Customer c = new Customer("C-1", "Acme", "not-an-email", "Leeds");
        assertEquals(1, validator.validate(c).size());
        c.setEmail("buyer@acme.test");
        assertTrue(validator.validate(c).isEmpty());
    }

    @Test
    public void totalSumsQuantityTimesPrice() {
        Order o = validOrder();
        o.getLines().add(new OrderLine("SKU-2", 1, new BigDecimal("0.02")));
        assertEquals(new BigDecimal("20.00"), OrderUtil.total(o));
        assertEquals(OrderStatus.RECEIVED, o.getStatus());
    }
}
