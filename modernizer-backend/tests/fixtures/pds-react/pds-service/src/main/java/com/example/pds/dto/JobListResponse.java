package com.example.pds.dto;
import java.util.List;
public class JobListResponse {
    private Tenant tenant;
    private String environment;
    private int total;
    private List<JobSummaryDto> jobs;
}
