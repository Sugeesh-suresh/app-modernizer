package com.acme.shop.web;
@ControllerAdvice
public class GlobalModel {
    @ModelAttribute("cartCount")
    public int cartCount(HttpSession session) {
        Cart cart = (Cart) session.getAttribute("cart");
        return cart == null ? 0 : cart.size();
    }
    @InitBinder
    public void trim(WebDataBinder binder) {
        binder.registerCustomEditor(String.class, new StringTrimmerEditor(true));
    }
}
