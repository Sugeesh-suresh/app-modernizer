package com.acme.store.web;

import com.acme.store.domain.Product;
import com.acme.store.search.ProductSearchService;
import com.acme.store.search.SearchUnavailableException;
import com.acme.store.service.Cart;
import com.acme.store.service.CatalogService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

/** The storefront's Thymeleaf pages. */
@Controller
public class StorePageController {

    @Autowired
    private CatalogService catalog;

    @Autowired
    private ProductSearchService search;

    @Autowired
    private Cart cart;

    @GetMapping("/")
    public String home(Model model) {
        model.addAttribute("topSellers", catalog.topSellers());
        return "home";
    }

    @GetMapping("/search")
    public String search(@RequestParam(value = "q", required = false) String q,
                         @RequestParam(value = "category", required = false) String category,
                         @RequestParam(value = "page", defaultValue = "0") int page, Model model) {
        model.addAttribute("q", q);
        model.addAttribute("category", category);
        try {
            model.addAttribute("result", search.search(q, category, null, null, null, null, page, 24));
        } catch (SearchUnavailableException e) {
            model.addAttribute("searchDown", true);
        }
        return "catalog/search";
    }

    @GetMapping("/products/{sku}")
    public String product(@PathVariable("sku") String sku, Model model) {
        Product product = catalog.bySku(sku);
        if (product == null) {
            return "error/404";
        }
        model.addAttribute("product", product);
        model.addAttribute("related", catalog.byCategory(product.getCategory()));
        return "catalog/product";
    }

    @GetMapping("/cart")
    public String cart(Model model) {
        model.addAttribute("cart", cart);
        return "cart/view";
    }

    @PostMapping("/cart/add")
    public String addToCart(@RequestParam("sku") String sku, @RequestParam(value = "qty", defaultValue = "1") int qty,
                            RedirectAttributes redirect) {
        Product product = catalog.bySku(sku);
        try {
            cart.add(product, qty);
            redirect.addFlashAttribute("message", product.getName() + " added to your cart");
        } catch (IllegalStateException e) {
            redirect.addFlashAttribute("error", e.getMessage());
        }
        return "redirect:/cart";
    }

    @PostMapping("/cart/remove")
    public String remove(@RequestParam("productId") Long productId) {
        cart.remove(productId);
        return "redirect:/cart";
    }

    @GetMapping("/admin/search")
    public String adminSearch() {
        return "admin/search-admin";
    }
}
