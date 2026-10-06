package com.acme.orders.api;

import com.acme.orders.dto.AttributeRow;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/attributes")
public class AttributeApiController {
    @GetMapping("/search")
    public List<AttributeRow> search(@RequestParam String q, @RequestParam(defaultValue = "false") boolean showValues) {
        return service.search(q, showValues);
    }
}
