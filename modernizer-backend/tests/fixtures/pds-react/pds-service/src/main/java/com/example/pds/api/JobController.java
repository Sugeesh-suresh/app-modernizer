package com.example.pds.api;

import com.example.pds.dto.*;
import com.example.pds.service.JobService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.time.LocalDate;
import java.util.List;

@RestController
@RequestMapping("/api/jobs")
public class JobController {
    private final JobService jobService;

    public JobController(JobService jobService) { this.jobService = jobService; }

    /** Job List page: every job of the tenant in the environment. */
    @GetMapping
    public JobListResponse listJobs(@RequestParam(defaultValue = "MCOM") Tenant tenant,
                                    @RequestParam(defaultValue = "DEV") String env,
                                    @RequestParam(defaultValue = "Standard") String view) {
        return jobService.list(tenant, env, view);
    }

    @GetMapping("/search")
    public JobListResponse searchJobs(@RequestParam("q") String query,
                                      @RequestParam(defaultValue = "VISIBLE") SearchScope scope,
                                      @RequestParam(defaultValue = "false") boolean exact,
                                      @RequestParam(defaultValue = "MCOM") Tenant tenant) {
        return jobService.search(query, scope, exact, tenant);
    }

    @GetMapping("/running")
    public List<JobExecutionDto> runningJobs() {
        return jobService.running();
    }

    @GetMapping("/completed")
    public List<JobExecutionDto> completedJobs(@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date) {
        return jobService.completed(date);
    }

    @GetMapping("/executions/{execId}/cancel")
    public ResponseEntity<Void> cancelExecution(@PathVariable("execId") Long execId) {
        if (!jobService.isRunning(execId)) {
            throw new JobNotRunningException(execId);
        }
        jobService.cancel(execId);
        return ResponseEntity.noContent().build();
    }
}
