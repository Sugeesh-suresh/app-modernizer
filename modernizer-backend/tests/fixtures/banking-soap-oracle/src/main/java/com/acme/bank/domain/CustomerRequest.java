package com.acme.bank.domain;

import javax.validation.constraints.Email;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Pattern;
import javax.validation.constraints.Size;

public class CustomerRequest {
    @NotBlank
    @Size(max = 120)
    public String fullName;

    @NotBlank
    @Email
    public String email;

    @Pattern(regexp = "RETAIL|PRIVATE|BUSINESS")
    public String segment;
}
