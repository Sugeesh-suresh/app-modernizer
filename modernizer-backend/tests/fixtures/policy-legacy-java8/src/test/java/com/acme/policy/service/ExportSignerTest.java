package com.acme.policy.service;

import static org.junit.Assert.assertEquals;

import com.acme.policy.util.ExportSigner;
import org.junit.Test;

public class ExportSignerTest {
    @Test
    public void blankPayloadIsNotSigned() throws Exception {
        assertEquals("", ExportSigner.sign("", "k"));
    }
}
