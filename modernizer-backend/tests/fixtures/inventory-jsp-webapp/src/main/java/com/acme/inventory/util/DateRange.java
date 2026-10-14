package com.acme.inventory.util;

import java.util.Date;

public class DateRange {
    private final Date start;
    private final Date end;

    public DateRange(Date start, Date end) {
        if (start == null || end == null) {
            throw new IllegalArgumentException("start and end are required");
        }
        if (end.before(start)) {
            throw new IllegalArgumentException("end before start");
        }
        this.start = new Date(start.getTime());
        this.end = new Date(end.getTime());
    }

    public boolean contains(Date d) {
        return d != null && !d.before(start) && !d.after(end);
    }

    public boolean overlaps(DateRange o) {
        return !o.end.before(start) && !o.start.after(end);
    }

    public long days() {
        return (end.getTime() - start.getTime()) / (24L * 60 * 60 * 1000);
    }
}
