package com.acme.policy.web;

import com.acme.policy.domain.Policy;
import com.acme.policy.search.PolicySearchService;
import com.acme.policy.service.PolicyService;
import java.util.List;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.bind.annotation.ResponseStatus;

@Controller
@RequestMapping("/policies")
public class PolicyController {

    @Autowired
    private PolicyService service;

    @Autowired
    private PolicySearchService search;

    @RequestMapping(method = RequestMethod.GET)
    @ResponseBody
    public List<Policy> list(@RequestParam(value = "status", required = false) String status) {
        return service.list(status);
    }

    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    @ResponseBody
    public Policy get(@PathVariable("id") Long id) {
        return service.get(id);
    }

    @RequestMapping(method = RequestMethod.POST)
    @ResponseStatus(HttpStatus.CREATED)
    @ResponseBody
    public Policy create(@RequestBody Policy policy) {
        return service.create(policy);
    }

    @RequestMapping(value = "/{id}", method = RequestMethod.DELETE)
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void cancel(@PathVariable("id") Long id) {
        service.cancel(id);
    }

    @RequestMapping(value = "/search", method = RequestMethod.GET)
    @ResponseBody
    public List<String> search(@RequestParam("holder") String holder) throws Exception {
        return search.searchByHolder(holder, 20);
    }
}
