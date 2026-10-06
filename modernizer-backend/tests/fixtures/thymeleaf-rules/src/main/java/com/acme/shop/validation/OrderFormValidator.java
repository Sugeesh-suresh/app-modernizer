package com.acme.shop.validation;
public class OrderFormValidator implements Validator {
    public boolean supports(Class<?> clazz) { return OrderForm.class.equals(clazz); }
    public void validate(Object target, Errors errors) {
        OrderForm form = (OrderForm) target;
        if (form.getQuantity() != null && form.getQuantity() > 10 && form.getEmail() == null) {
            errors.rejectValue("email", "order.email.required.bulk");
        }
    }
}
