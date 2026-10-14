package com.acme.shop.web;

import com.acme.shop.model.Product;
import com.acme.shop.service.ProductService;
import javax.validation.Valid;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class ProductController {

    private final ProductService service;

    @Autowired
    public ProductController(ProductService service) {
        this.service = service;
    }

    @RequestMapping(value = "/products", method = RequestMethod.GET)
    public String list(@RequestParam(value = "q", required = false, defaultValue = "") String q,
                       @RequestParam(value = "page", required = false, defaultValue = "0") int page,
                       Model model) {
        model.addAttribute("products", service.search(q, page));
        model.addAttribute("q", q);
        model.addAttribute("page", page);
        model.addAttribute("pages", service.pageCount(q));
        return "products/list";
    }

    @RequestMapping(value = "/products/{id}", method = RequestMethod.GET)
    public String detail(@PathVariable("id") long id, Model model) {
        Product p = service.get(id);
        model.addAttribute("product", p);
        model.addAttribute("formattedPrice", service.formatPrice(p.getPrice()));
        return "products/detail";
    }

    @RequestMapping(value = "/products/new", method = RequestMethod.GET)
    public String newForm(Model model) {
        model.addAttribute("product", new Product());
        return "products/form";
    }

    @RequestMapping(value = "/products", method = RequestMethod.POST)
    public String create(@Valid Product product, BindingResult result, RedirectAttributes redirect) {
        if (result.hasErrors()) {
            return "products/form";
        }
        Product saved = service.create(product);
        redirect.addFlashAttribute("message", "product.created");
        return "redirect:/products/" + saved.getId();
    }

    @RequestMapping(value = "/api/products/{id}", method = RequestMethod.GET, produces = "application/json")
    @ResponseBody
    public Product json(@PathVariable("id") long id) {
        return service.get(id);
    }
}
