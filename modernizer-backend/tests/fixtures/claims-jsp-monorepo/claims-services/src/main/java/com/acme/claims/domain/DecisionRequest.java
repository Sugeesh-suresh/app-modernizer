package com.acme.claims.domain;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Pattern;

public class DecisionRequest {
    @NotBlank
    @Pattern(regexp = "APPROVED|REJECTED")
    public String decision;
}
