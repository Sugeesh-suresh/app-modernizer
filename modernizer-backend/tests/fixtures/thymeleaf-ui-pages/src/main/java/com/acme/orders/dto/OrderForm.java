package com.acme.orders.dto;
import javax.validation.constraints.*;
public class OrderForm {
    @NotBlank @Size(max = 80)
    private String customer;
    @NotNull @Min(1) @Max(50)
    private Integer quantity;
    @Email
    private String email;
}
