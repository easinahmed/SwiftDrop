package com.swiftdrop.android.youtube

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CookiesTxtTest {

    private val now = 1_800_000_000L
    private val header = "SID=sid-secret-value; __Secure-3PAPISID=papisid/secret=; PREF=f6=40000000&tz=UTC; __Host-GAPS=host-secret"

    @Test
    fun parseHeader_keepsValuesWithEqualsSigns() {
        assertEquals(
            listOf("a" to "b=c", "d" to ""),
            CookiesTxt.parseHeader("a=b=c; d=; =nameless; junk"),
        )
        assertEquals(emptyList<Pair<String, String>>(), CookiesTxt.parseHeader(null))
    }

    @Test
    fun write_isNetscapeFormat() {
        val text = CookiesTxt.write(CookiesTxt.entries("www.youtube.com", "youtube.com", header, now))
        val lines = text.lines()
        assertEquals("# Netscape HTTP Cookie File", lines.first())
        val cookies = lines.filter { it.isNotBlank() && !it.startsWith("#") }
        assertEquals(4, cookies.size)
        cookies.forEach { assertEquals(it, 7, it.split('\t').size) }
        assertEquals(".youtube.com\tTRUE\t/\tTRUE\t${now + 365L * 24 * 3600}\tSID\tsid-secret-value", cookies[0])
        assertTrue(cookies.contains(".youtube.com\tTRUE\t/\tTRUE\t${now + 365L * 24 * 3600}\t__Secure-3PAPISID\tpapisid/secret="))
        // __Host- cookies stay on their exact host.
        assertTrue(cookies.any { it.startsWith("www.youtube.com\tFALSE\t/\tTRUE\t") && it.endsWith("\t__Host-GAPS\thost-secret") })
        assertTrue(text.endsWith("\n"))
    }

    @Test
    fun write_dropsLinesThatWouldBreakTheFormat_andDuplicates() {
        val entries = listOf(
            CookieEntry(".youtube.com", true, "/", true, 1, "OK", "v"),
            CookieEntry(".youtube.com", true, "/", true, 1, "OK", "second"),
            CookieEntry(".youtube.com", true, "/", true, 1, "BAD", "tab\there"),
            CookieEntry(".youtube.com", true, "/", true, 1, "NL", "line\nbreak"),
        )
        val cookies = CookiesTxt.write(entries).lines().filter { it.isNotBlank() && !it.startsWith("#") }
        assertEquals(listOf(".youtube.com\tTRUE\t/\tTRUE\t1\tOK\tv"), cookies)
    }

    @Test
    fun hasLogin_onlyWithAnAccountCookieForThatSite() {
        val signedIn = CookiesTxt.write(CookiesTxt.entries("www.youtube.com", "youtube.com", header, now))
        assertTrue(CookiesTxt.hasLogin(signedIn, "youtube.com"))
        val visitor = CookiesTxt.write(CookiesTxt.entries("www.youtube.com", "youtube.com", "YSC=x; VISITOR_INFO1_LIVE=y", now))
        assertFalse(CookiesTxt.hasLogin(visitor, "youtube.com"))
        // Mid sign-in: Google's session exists, YouTube's doesn't yet.
        val googleOnly = CookiesTxt.write(
            CookiesTxt.entries("accounts.google.com", "google.com", "SID=g; __Secure-3PSID=g3", now) +
                CookiesTxt.entries("www.youtube.com", "youtube.com", "YSC=x", now)
        )
        assertTrue(CookiesTxt.hasLogin(googleOnly, "google.com"))
        assertFalse(CookiesTxt.hasLogin(googleOnly, "youtube.com"))
    }

    @Test
    fun toString_neverShowsCookieValues() {
        val entries = CookiesTxt.entries("www.youtube.com", "youtube.com", header, now)
        val printed = entries.joinToString() + entries.toString()
        assertFalse(printed, printed.contains("sid-secret-value"))
        assertFalse(printed, printed.contains("papisid/secret"))
        assertFalse(printed, printed.contains("host-secret"))
        assertTrue(printed.contains("SID")) // names are fine
    }
}
