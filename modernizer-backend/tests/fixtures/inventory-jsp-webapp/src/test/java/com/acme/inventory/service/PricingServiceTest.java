package com.acme.inventory.service;

import static org.junit.Assert.assertEquals;

import com.acme.inventory.model.Order;
import com.acme.inventory.model.OrderLine;
import java.math.BigDecimal;
import org.junit.Before;
import org.junit.Test;

public class PricingServiceTest {
    private PricingService service;

    @Before
    public void setUp() {
        service = new PricingService();
    }

    @Test
    public void discountRate_subtotalAtTopTier_returnsTenPercent() {
        assertEquals(new BigDecimal("0.10"), service.discountRate(new BigDecimal("1000")));
    }

    @Test
    public void discountRate_smallSubtotal_returnsZero() {
        assertEquals(BigDecimal.ZERO, service.discountRate(new BigDecimal("99.99")));
    }

    @Test(expected = IllegalArgumentException.class)
    public void discountRate_negativeSubtotal_throws() {
        service.discountRate(new BigDecimal("-1"));
    }

    @Test
    public void taxRate_knownRegion_returnsRate() {
        assertEquals(new BigDecimal("0.07"), service.taxRate("us"));
    }

    @Test
    public void total_euOrderWithDiscount_roundsHalfUp() {
        // 600 - 5% = 570.00; + 20% VAT = 684.00
        assertEquals(new BigDecimal("684.00"), service.total(new BigDecimal("600"), "EU"));
    }

    @Test(expected = IllegalArgumentException.class)
    public void taxRate_blankRegion_throws() {
        service.taxRate("  ");
    }

    @Test
    public void total_orderSubtotalWithTwoLines_appliesSmallDiscountAndTax() {
        Order order = new Order();
        order.setRegion("US");
        order.addLine(new OrderLine(1, 2, new BigDecimal("40.00")));
        order.addLine(new OrderLine(2, 1, new BigDecimal("30.00")));
        // 110.00 - 2% = 107.80; + 7% = 115.346 -> 115.35
        assertEquals(new BigDecimal("115.35"), service.total(order.getSubtotal(), order.getRegion()));
    }

    @Test
    public void taxRate_unknownRegion_returnsZero() {
        assertEquals(BigDecimal.ZERO, service.taxRate("ZZ"));
    }

    @Test
    public void taxRate_japan_returnsTenPercent() {
        assertEquals(new BigDecimal("0.10"), service.taxRate("JP"));
    }
}
