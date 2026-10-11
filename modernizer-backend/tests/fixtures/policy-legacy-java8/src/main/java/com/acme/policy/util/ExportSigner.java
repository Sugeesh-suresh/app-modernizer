package com.acme.policy.util;

import java.security.MessageDigest;
import javax.xml.bind.DatatypeConverter;
import org.apache.commons.lang.StringUtils;
import sun.misc.BASE64Encoder;

/** Signs CSV exports for the legacy reporting system. */
public final class ExportSigner {
    private ExportSigner() {
    }

    public static String sign(String payload, String key) throws Exception {
        if (StringUtils.isBlank(payload)) {
            return "";
        }
        MessageDigest md5 = MessageDigest.getInstance("MD5");
        byte[] digest = md5.digest((key + payload).getBytes("UTF-8"));
        return new BASE64Encoder().encode(digest);
    }

    public static String hex(byte[] bytes) {
        return DatatypeConverter.printHexBinary(bytes);
    }
}
