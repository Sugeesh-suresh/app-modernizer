package com.acme.orders.api;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import javax.servlet.FilterChain;

import org.junit.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import com.acme.orders.api.filter.CorrelationIdFilter;

public class CorrelationIdFilterTest {

    private final CorrelationIdFilter filter = new CorrelationIdFilter();

    @Test
    public void reusesIncomingHeaderAndClearsMdcAfterwards() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest("GET", "/api/health");
        req.addHeader(CorrelationIdFilter.HEADER, "abc-123");
        MockHttpServletResponse res = new MockHttpServletResponse();
        final String[] seen = new String[1];
        FilterChain chain = (rq, rs) -> seen[0] = MDC.get(CorrelationIdFilter.MDC_KEY);

        filter.doFilter(req, res, chain);

        assertEquals("abc-123", seen[0]);
        assertEquals("abc-123", res.getHeader(CorrelationIdFilter.HEADER));
        assertNull(MDC.get(CorrelationIdFilter.MDC_KEY));
    }

    @Test
    public void generatesIdWhenMissing() throws Exception {
        MockHttpServletResponse res = new MockHttpServletResponse();
        filter.doFilter(new MockHttpServletRequest("GET", "/api/orders"), res, (rq, rs) -> { });
        assertNotNull(res.getHeader(CorrelationIdFilter.HEADER));
    }
}
