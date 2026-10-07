package com.acme.orders.web;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class JobListController {
    @GetMapping("/selfservicetool/job_list")
    public String jobList() {
        return "selfservicetool/job_list";
    }
}
