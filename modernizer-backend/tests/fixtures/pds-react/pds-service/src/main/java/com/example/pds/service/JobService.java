package com.example.pds.service;
import com.example.pds.dto.*;
import java.time.LocalDate;
import java.util.List;
public interface JobService {
    JobListResponse list(Tenant tenant, String env, String view);
    JobListResponse search(String query, SearchScope scope, boolean exact, Tenant tenant);
    List<JobExecutionDto> running();
    List<JobExecutionDto> completed(LocalDate date);
    boolean isRunning(Long execId);
    void cancel(Long execId);
}
