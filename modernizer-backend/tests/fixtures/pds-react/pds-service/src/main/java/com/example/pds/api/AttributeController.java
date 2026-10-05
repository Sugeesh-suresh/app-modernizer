package com.example.pds.api;

import com.example.pds.dto.AttributeDto;
import com.example.pds.service.AttributeService;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.data.domain.Page;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/attributes")
public class AttributeController {
    private final AttributeService attributeService;

    public AttributeController(AttributeService attributeService) { this.attributeService = attributeService; }

    @GetMapping
    public Page<AttributeDto> listAttributes(@RequestParam(defaultValue = "0") @Min(0) int page,
                                             @RequestParam(defaultValue = "20") @Min(1) @Max(100) int size,
                                             @RequestParam(defaultValue = "false") boolean showValues) {
        return attributeService.list(page, size, showValues);
    }

    @GetMapping("/search")
    public Page<AttributeDto> searchAttributes(@RequestParam(required = false) Long id,
                                               @RequestParam(required = false) String name,
                                               @RequestParam(defaultValue = "0") int page) {
        return attributeService.search(id, name, page);
    }

    @GetMapping("/{id}")
    public AttributeDto getAttribute(@PathVariable Long id) {
        return attributeService.find(id).orElseThrow(() -> new AttributeNotFoundException(id));
    }
}
