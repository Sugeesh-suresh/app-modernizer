package com.acme.store.search;

public class SearchUnavailableException extends RuntimeException {
    public SearchUnavailableException(Throwable cause) {
        super("Search is temporarily unavailable", cause);
    }
}
