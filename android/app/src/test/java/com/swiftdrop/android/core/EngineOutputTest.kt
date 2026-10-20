package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EngineOutputTest {

    @Test
    fun speed_isParsedFromProgressLine() {
        assertEquals("1.23MiB/s", EngineOutput.speed("[download]  12.3% of   10.00MiB at    1.23MiB/s ETA 00:05"))
        assertEquals("512.00KiB/s", EngineOutput.speed("[download]  50.0% of ~  3.00MiB at  512.00KiB/s ETA 00:03 (frag 2/9)"))
        assertNull(EngineOutput.speed("[download]  12.3% of 10.00MiB at Unknown B/s ETA Unknown"))
        assertNull(EngineOutput.speed(null))
    }

    @Test
    fun readableError_picksLastErrorLineAndStripsPrefixes() {
        val stderr = """
            WARNING: [youtube] something minor
            ERROR: [youtube] dQw4w9WgXcQ: Private video. Sign in if you've been granted access
        """.trimIndent()
        assertEquals("This video is private.", EngineOutput.readableError(stderr))
        assertEquals(
            "This link isn't supported.",
            EngineOutput.readableError("ERROR: Unsupported URL: https://example.com/"),
        )
        assertEquals("Download failed.", EngineOutput.readableError(""))
        assertEquals("Something odd", EngineOutput.readableError("ERROR: Something odd"))
    }
}
