package com.acme.shop.web;
@FeignClient(name = "shipping", url = "${shipping.url}")
public interface ShippingClient {
    @GetMapping("/rates")
    Rates rates(String zip);
}
