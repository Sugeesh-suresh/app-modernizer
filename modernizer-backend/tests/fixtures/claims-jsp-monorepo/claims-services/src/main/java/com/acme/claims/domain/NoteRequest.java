package com.acme.claims.domain;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;

public class NoteRequest {
    @NotBlank
    @Size(max = 500)
    public String text;
}
