package com.example.pds.dto;
import com.fasterxml.jackson.annotation.JsonFormat;
import java.time.LocalDateTime;
public class JobExecutionDto {
    private Long jobId;
    private String jobName;
    private Long jobExecId;
    private Long asyncJobId;
    private ExecutionStatus status;
    @JsonFormat(pattern = "MM/dd/yy hh:mm a")
    private LocalDateTime started;
    private String elapsedTime;
}
