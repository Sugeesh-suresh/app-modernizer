package com.acme.inventory.util;

public final class InputValidator {
    private InputValidator() {
    }

    public static boolean isBlank(String s) {
        return s == null || s.trim().isEmpty();
    }

    public static int parsePositiveInt(String s, int defaultValue) {
        if (isBlank(s)) {
            return defaultValue;
        }
        try {
            int v = Integer.parseInt(s.trim());
            return v > 0 ? v : defaultValue;
        } catch (NumberFormatException e) {
            return defaultValue;
        }
    }

    public static boolean isValidSku(String sku) {
        return sku != null && sku.matches("[A-Z]{2,4}-\\d{3,6}");
    }

    public static boolean isValidEmail(String email) {
        if (isBlank(email)) {
            return false;
        }
        int at = email.indexOf('@');
        return at > 0 && at == email.lastIndexOf('@') && email.indexOf('.', at) > at + 1
                && !email.endsWith(".");
    }

    public static String sanitize(String s) {
        if (s == null) {
            return "";
        }
        return s.trim().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
