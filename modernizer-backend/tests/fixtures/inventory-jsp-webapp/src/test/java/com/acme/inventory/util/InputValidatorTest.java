package com.acme.inventory.util;

import static org.hamcrest.CoreMatchers.is;
import static org.junit.Assert.assertThat;

import org.junit.Test;

public class InputValidatorTest {

    @Test
    public void isBlank_nullInput_returnsTrue() {
        assertThat(InputValidator.isBlank(null), is(true));
    }

    @Test
    public void isBlank_textInput_returnsFalse() {
        assertThat(InputValidator.isBlank(" a "), is(false));
    }

    @Test
    public void parsePositiveInt_validNumber_returnsNumber() {
        assertThat(InputValidator.parsePositiveInt("7", 1), is(7));
    }

    @Test
    public void parsePositiveInt_garbage_returnsDefault() {
        assertThat(InputValidator.parsePositiveInt("abc", 3), is(3));
    }

    @Test
    public void parsePositiveInt_negative_returnsDefault() {
        assertThat(InputValidator.parsePositiveInt("-5", 2), is(2));
    }

    @Test
    public void isValidSku_wellFormed_returnsTrue() {
        assertThat(InputValidator.isValidSku("ABC-1234"), is(true));
    }

    @Test
    public void isValidSku_lowerCase_returnsFalse() {
        assertThat(InputValidator.isValidSku("abc-1234"), is(false));
    }

    @Test
    public void sanitize_htmlCharacters_areEscaped() {
        assertThat(InputValidator.sanitize("<b>\"x\"</b>"), is("&lt;b&gt;&quot;x&quot;&lt;/b&gt;"));
    }

    @Test
    public void isValidEmail_plainAddress_returnsTrue() {
        assertThat(InputValidator.isValidEmail("a@b.com"), is(true));
    }

    @Test
    public void isValidEmail_missingAt_returnsFalse() {
        assertThat(InputValidator.isValidEmail("ab.com"), is(false));
    }

    @Test
    public void sanitize_nullInput_returnsEmptyString() {
        assertThat(InputValidator.sanitize(null), is(""));
    }
}
