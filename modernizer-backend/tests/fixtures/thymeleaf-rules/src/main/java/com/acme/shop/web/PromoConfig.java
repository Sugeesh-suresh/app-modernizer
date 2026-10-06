package com.acme.shop.web;
@Configuration
@ConditionalOnProperty(name = "promo.enabled", havingValue = "true")
public class PromoConfig {
    @Value("#{${promo.rate} * 100}")
    private int percent;
    public Object discount(String rule, Object order) {
        return new SpelExpressionParser().parseExpression(rule).getValue(order);
    }
}
