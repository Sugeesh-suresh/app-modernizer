package com.acme.bank.legacy;

import java.math.BigDecimal;

@Deprecated
public class InterestCalculator {
    public BigDecimal monthly(BigDecimal balance) {
        System.out.println("calculating interest");
        return balance.multiply(new BigDecimal("0.0025"));
    }
}
