package com.example.pds.api;
public class JobNotRunningException extends RuntimeException { public JobNotRunningException(Long id) { super("Job execution " + id + " is not running"); } }
