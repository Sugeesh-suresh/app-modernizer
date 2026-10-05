package com.example.pds.api;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(JobNotRunningException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public String notRunning(JobNotRunningException e) { return e.getMessage(); }

    @ExceptionHandler(AttributeNotFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public String notFound(AttributeNotFoundException e) { return e.getMessage(); }
}
