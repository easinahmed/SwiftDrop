package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LinkExtractorTest {

    @Test
    fun youtubeShareText_returnsLinkWithoutSi() {
        val shared = "Never Gonna Give You Up https://youtu.be/dQw4w9WgXcQ?si=Ab12Cd34Ef56Gh78"
        assertEquals("https://youtu.be/dQw4w9WgXcQ", LinkExtractor.firstUrl(shared))
    }

    @Test
    fun youtubeShorts_stripsSiOnly() {
        assertEquals(
            "https://youtube.com/shorts/aqz-KE-bpKQ",
            LinkExtractor.firstUrl("https://youtube.com/shorts/aqz-KE-bpKQ?si=xYz123"),
        )
    }

    @Test
    fun youtubeWatch_keepsVideoIdPlaylistAndTimestamp() {
        val url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=abc&list=PL123&t=42&feature=shared"
        assertEquals(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42",
            LinkExtractor.firstUrl(url),
        )
    }

    @Test
    fun chromeShare_bareUrl() {
        assertEquals(
            "https://example.com/media/clip.mp4",
            LinkExtractor.firstUrl("https://example.com/media/clip.mp4"),
        )
    }

    @Test
    fun chromeShare_titleThenUrlOnNewLine() {
        assertEquals(
            "https://news.example.org/story/123",
            LinkExtractor.firstUrl("Big story of the day\nhttps://news.example.org/story/123"),
        )
    }

    @Test
    fun textWithoutUrl_returnsNull() {
        assertNull(LinkExtractor.firstUrl("just some words, no link here"))
        assertNull(LinkExtractor.firstUrl(""))
        assertNull(LinkExtractor.firstUrl("   "))
        assertNull(LinkExtractor.firstUrl(null))
        assertNull(LinkExtractor.firstUrl("ftp://files.example.com/a.zip and mailto:me@example.com"))
        assertNull(LinkExtractor.firstUrl("broken http:// link"))
    }

    @Test
    fun multipleUrls_returnsFirst() {
        val text = "first https://a.example.com/one then https://b.example.com/two"
        assertEquals("https://a.example.com/one", LinkExtractor.firstUrl(text))
    }

    @Test
    fun plainHttpAndPorts_areAccepted() {
        assertEquals(
            "http://10.0.2.2:8000/test.mp4",
            LinkExtractor.firstUrl("Look http://10.0.2.2:8000/test.mp4"),
        )
    }

    @Test
    fun trailingPunctuation_isTrimmed() {
        assertEquals("https://example.com/v/1", LinkExtractor.firstUrl("Watch this: https://example.com/v/1."))
        assertEquals("https://example.com/v/2", LinkExtractor.firstUrl("(see https://example.com/v/2)"))
        assertEquals("https://example.com/v/3", LinkExtractor.firstUrl("\"https://example.com/v/3\","))
    }

    @Test
    fun balancedParentheses_areKept() {
        assertEquals(
            "https://en.wikipedia.org/wiki/Foo_(bar)",
            LinkExtractor.firstUrl("see https://en.wikipedia.org/wiki/Foo_(bar)."),
        )
    }

    @Test
    fun utmAndClickIds_areStrippedEverywhere() {
        assertEquals(
            "https://example.com/v?id=3",
            LinkExtractor.firstUrl("https://example.com/v?id=3&utm_source=x&utm_medium=y&fbclid=zz"),
        )
        assertEquals(
            "https://example.com/v",
            LinkExtractor.firstUrl("https://example.com/v?utm_campaign=spring&gclid=1"),
        )
    }

    @Test
    fun siIsKeptOnUnrelatedSites() {
        assertEquals(
            "https://files.example.com/get?si=42",
            LinkExtractor.firstUrl("https://files.example.com/get?si=42"),
        )
    }

    @Test
    fun fragmentIsPreserved() {
        assertEquals(
            "https://example.com/page?a=1#section",
            LinkExtractor.firstUrl("https://example.com/page?a=1&utm_source=x#section"),
        )
    }

    @Test
    fun instagramAndTwitterTracking() {
        assertEquals(
            "https://www.instagram.com/reel/C0abc/",
            LinkExtractor.firstUrl("https://www.instagram.com/reel/C0abc/?igsh=MWQ1ZGUxMzBkMA=="),
        )
        assertEquals(
            "https://x.com/someone/status/123",
            LinkExtractor.firstUrl("https://x.com/someone/status/123?s=46&t=AbCdEf"),
        )
    }

    @Test
    fun uppercaseScheme_isRecognised() {
        assertEquals("HTTPS://Example.com/A", LinkExtractor.firstUrl("go to HTTPS://Example.com/A now"))
    }

    @Test
    fun hostOf_normalises() {
        assertEquals("youtube.com", LinkExtractor.hostOf("https://www.YouTube.com/watch?v=x"))
        assertEquals("10.0.2.2", LinkExtractor.hostOf("http://10.0.2.2:8000/a"))
        assertEquals("example.com", LinkExtractor.hostOf("https://user:pw@example.com/a"))
    }
}
