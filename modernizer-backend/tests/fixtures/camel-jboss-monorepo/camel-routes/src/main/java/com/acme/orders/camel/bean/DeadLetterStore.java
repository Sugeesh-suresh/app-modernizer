package com.acme.orders.camel.bean;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/** In-memory sink for messages that ended up on direct:deadLetter. */
public class DeadLetterStore {

    public static class Entry {
        private final Object body;
        private final String reason;

        public Entry(Object body, String reason) {
            this.body = body;
            this.reason = reason;
        }

        public Object getBody() { return body; }
        public String getReason() { return reason; }
    }

    private final List<Entry> entries = new CopyOnWriteArrayList<Entry>();

    public void add(Object body, String reason) {
        entries.add(new Entry(body, reason));
    }

    public List<Entry> getEntries() {
        return entries;
    }

    public void clear() {
        entries.clear();
    }
}
