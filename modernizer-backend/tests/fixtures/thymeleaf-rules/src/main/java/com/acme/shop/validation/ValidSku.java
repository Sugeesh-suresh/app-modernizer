package com.acme.shop.validation;
@Constraint(validatedBy = SkuValidator.class)
@Target(ElementType.FIELD)
@Retention(RetentionPolicy.RUNTIME)
public @interface ValidSku {
    String message() default "{sku.invalid}";
}
