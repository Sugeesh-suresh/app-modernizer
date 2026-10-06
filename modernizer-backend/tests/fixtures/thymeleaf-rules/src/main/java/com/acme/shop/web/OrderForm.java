package com.acme.shop.web;
import com.acme.shop.validation.ValidSku;
public class OrderForm {
    @NotNull
    @Max(value = 50, message = "{order.quantity.max}")
    private Integer quantity;
    @Email(message = "{order.email.invalid}")
    private String email;
    @ValidSku
    private String sku;
}
