package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class YouTubeIdsTest {

    @Test
    fun videoId_fromEveryLinkShape() {
        assertEquals("dQw4w9WgXcQ", YouTubeIds.videoId("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42"))
        assertEquals("dQw4w9WgXcQ", YouTubeIds.videoId("https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ"))
        assertEquals("dQw4w9WgXcQ", YouTubeIds.videoId("https://youtu.be/dQw4w9WgXcQ?si=abc"))
        assertEquals("aqz-KE-bpKQ", YouTubeIds.videoId("https://www.youtube.com/shorts/aqz-KE-bpKQ"))
        assertEquals("aqz-KE-bpKQ", YouTubeIds.videoId("https://youtube.com/embed/aqz-KE-bpKQ?start=3"))
        assertEquals("aqz-KE-bpKQ", YouTubeIds.videoId("https://www.youtube.com/live/aqz-KE-bpKQ"))
        assertEquals("dQw4w9WgXcQ", YouTubeIds.videoId("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD"))
    }

    @Test
    fun videoId_nullForOtherLinks() {
        assertNull(YouTubeIds.videoId("https://www.youtube.com/playlist?list=PL123"))
        assertNull(YouTubeIds.videoId("https://vimeo.com/123456"))
        assertNull(YouTubeIds.videoId("https://www.youtube.com/watch?v=short"))
    }

    @Test
    fun thumbnailAndHostCheck() {
        assertEquals("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg", YouTubeIds.thumbnail("dQw4w9WgXcQ"))
        assertTrue(YouTubeIds.isYouTubeUrl("https://youtu.be/dQw4w9WgXcQ"))
        assertFalse(YouTubeIds.isYouTubeUrl("https://notyoutube.com/watch?v=dQw4w9WgXcQ"))
    }
}
