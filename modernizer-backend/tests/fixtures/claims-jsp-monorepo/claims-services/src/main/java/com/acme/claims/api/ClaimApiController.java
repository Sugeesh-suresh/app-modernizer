package com.acme.claims.api;

import com.acme.claims.domain.Claim;
import com.acme.claims.domain.DecisionRequest;
import com.acme.claims.domain.NoteRequest;
import com.acme.claims.service.ClaimService;
import java.util.List;
import javax.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/claims")
public class ClaimApiController {
    private final ClaimService service;

    public ClaimApiController(ClaimService service) {
        this.service = service;
    }

    @GetMapping
    public List<Claim> list(@RequestParam(required = false) String status) {
        return service.list(status);
    }

    @GetMapping("/search")
    public List<Claim> search(@RequestParam String policy) {
        return service.search(policy);
    }

    @GetMapping("/{id}")
    public Claim get(@PathVariable Long id) {
        return service.get(id);
    }

    @PutMapping("/{id}/decision")
    public Claim decide(@PathVariable Long id, @Valid @RequestBody DecisionRequest request) {
        return service.decide(id, request.decision);
    }

    @PostMapping("/{id}/notes")
    @ResponseStatus(HttpStatus.CREATED)
    public void addNote(@PathVariable Long id, @Valid @RequestBody NoteRequest request) {
        service.addNote(id, request.text);
    }

    @GetMapping("/export")
    public String export(@RequestParam(required = false) String status) {
        StringBuilder csv = new StringBuilder("id,policy,amount,status\n");
        for (Claim c : service.list(status)) {
            csv.append(c.getId()).append(',').append(c.getPolicyNumber()).append(',').append(c.getAmount())
               .append(',').append(c.getStatus()).append('\n');
        }
        return csv.toString();
    }

    @DeleteMapping("/{id}")
    public void purge(@PathVariable Long id) {
        // FIXME: soft delete only; never wired into the UI
        throw new UnsupportedOperationException();
    }
}
