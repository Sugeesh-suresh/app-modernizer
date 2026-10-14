package com.acme.orders.api.error;

import java.util.LinkedHashMap;
import java.util.Map;

/** JSON error body returned for every failed request. */
public class ApiError {
    private int status;
    private String error;
    private String message;
    private Map<String, String> fieldErrors = new LinkedHashMap<String, String>();

    public ApiError() {
    }

    public ApiError(int status, String error, String message) {
        this.status = status;
        this.error = error;
        this.message = message;
    }

    public int getStatus() { return status; }
    public void setStatus(int status) { this.status = status; }
    public String getError() { return error; }
    public void setError(String error) { this.error = error; }
    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public Map<String, String> getFieldErrors() { return fieldErrors; }
    public void setFieldErrors(Map<String, String> fieldErrors) { this.fieldErrors = fieldErrors; }
}
