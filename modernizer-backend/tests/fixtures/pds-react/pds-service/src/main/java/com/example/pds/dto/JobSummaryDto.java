package com.example.pds.dto;
import java.util.List;
public class JobSummaryDto {
    private Long jobId;
    private String jobName;
    private JobState status;
    private Integer attributeId;
    private String attributeType;
    private boolean editable;
    private boolean runnable;
    private boolean nonApprovedOnly;
    private List<String> warnings;
}
