package com.acme.catalog.web;

import com.acme.catalog.jobs.ReindexJob;
import com.acme.catalog.repo.ProductRepository;
import com.acme.catalog.search.ProductSearchService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class CatalogPageController {
    private final ProductSearchService search;
    private final ProductRepository products;
    private final ReindexJob reindex;

    public CatalogPageController(ProductSearchService search, ProductRepository products, ReindexJob reindex) {
        this.search = search;
        this.products = products;
        this.reindex = reindex;
    }

    @GetMapping("/")
    public String home(Model model) {
        return "home";
    }

    @GetMapping("/search")
    public String results(@RequestParam(defaultValue = "") String q, @RequestParam(required = false) String category,
                          Model model) throws Exception {
        model.addAttribute("q", q);
        model.addAttribute("results", search.search(q, category, false, 0));
        return "search/results";
    }

    @GetMapping("/products/{sku}")
    public String detail(@PathVariable String sku, Model model) {
        model.addAttribute("product", products.findById(sku).orElseThrow());
        return "products/detail";
    }

    @GetMapping("/admin/reindex")
    public String reindexPage() {
        return "admin/reindex";
    }

    @PostMapping("/admin/reindex")
    public String reindex(RedirectAttributes flash) throws Exception {
        reindex.full();
        flash.addFlashAttribute("message", "Full reindex finished");
        return "redirect:/admin/reindex";
    }
}
