package com.acme.orders.api;

import com.acme.orders.dto.JobRow;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/jobs")
public class JobApiController {
    @GetMapping
    public List<JobRow> all() {
        return service.findAll();
    }
}
