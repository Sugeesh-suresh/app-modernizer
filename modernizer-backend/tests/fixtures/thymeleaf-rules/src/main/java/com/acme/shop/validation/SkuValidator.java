package com.acme.shop.validation;
public class SkuValidator implements ConstraintValidator<ValidSku, String> {
    @Override
    public boolean isValid(String value, ConstraintValidatorContext ctx) {
        return value != null && value.matches("[A-Z]{3}-\\d{4}");
    }
}
