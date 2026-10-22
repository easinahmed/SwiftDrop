package com.swiftdrop.android.engine

import java.io.FileNotFoundException
import java.io.IOException
import java.net.UnknownHostException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EngineErrorsTest {

    private fun wrapped(cause: Throwable) = Exception("failed to update youtube-dl", cause)

    @Test
    fun githubRateLimit_isExplainedPlainly() {
        val message = EngineErrors.describeUpdateFailure(
            wrapped(IOException("Server returned HTTP response code: 403 for URL: https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"))
        )
        assertEquals(EngineErrors.RATE_LIMITED, message)
        assertTrue(message.contains("GitHub is limiting update checks"))
    }

    @Test
    fun offlineAndUnreachable() {
        assertEquals(EngineErrors.OFFLINE, EngineErrors.describeUpdateFailure(wrapped(UnknownHostException("api.github.com"))))
        assertEquals(EngineErrors.UNREACHABLE, EngineErrors.describeUpdateFailure(wrapped(FileNotFoundException("https://github.com/x"))))
        assertEquals(EngineErrors.UNREACHABLE, EngineErrors.describeUpdateFailure(wrapped(IOException("timeout"))))
        assertEquals("Something else", EngineErrors.describeUpdateFailure(Exception("Something else\nmore")))
    }

    @Test
    fun staleness_isThreeDays() {
        val now = 10_000_000_000L
        val threeDays = 3L * 24 * 3600 * 1000
        assertTrue(EngineErrors.isStale(0L, now, threeDays))
        assertTrue(EngineErrors.isStale(now - threeDays, now, threeDays))
        assertFalse(EngineErrors.isStale(now - threeDays + 1, now, threeDays))
    }
}
