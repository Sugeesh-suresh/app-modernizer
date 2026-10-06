package com.acme.shop.web;
@Controller
@SessionAttributes("checkoutStep")
public class OrderController {
    @PostMapping("/orders")
    public String place(@Valid OrderForm form, BindingResult result, RedirectAttributes flash, HttpSession session) {
        if (result.hasErrors()) {
            return "orders/form";
        }
        session.setAttribute("lastOrder", form.getSku());
        flash.addFlashAttribute("message", "Order placed");
        return "redirect:/orders";
    }
    @ExceptionHandler(OutOfStockException.class)
    public String outOfStock(Model model) {
        model.addAttribute("error", "That item is out of stock");
        return "orders/form";
    }
    public List<Order> history(long customerId) {
        return jdbc.query("SELECT * FROM orders o JOIN order_audit a ON a.order_id = o.id WHERE o.customer_id = ?", mapper, customerId);
    }
    public void archive(long id) {
        jdbc.call("{call archive_order(?)}", id);
    }
}
