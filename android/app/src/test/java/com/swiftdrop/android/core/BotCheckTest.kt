package com.swiftdrop.android.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BotCheckTest {

    @Test
    fun signInToConfirmNotABot_curlyAndStraightApostrophe() {
        assertTrue(
            BotCheck.isBotCheck(
                "ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you’re not a bot. Use --cookies-from-browser or " +
                    "--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ"
            )
        )
        assertTrue(BotCheck.isBotCheck("ERROR: [youtube] abc: Sign in to confirm you're not a bot"))
        assertTrue(BotCheck.isBotCheck("WARNING: x\nERROR: [youtube] abc: Sign in to confirm that you are human"))
    }

    @Test
    fun loginRequiredAndRateLimitAndWithheldFormats() {
        assertTrue(BotCheck.isBotCheck("ERROR: [youtube] abc: playability status: LOGIN_REQUIRED"))
        assertTrue(BotCheck.isBotCheck("ERROR: [youtube] abc: This content isn't available, try again later."))
        assertTrue(BotCheck.isBotCheck("ERROR: [youtube] abc: Only images are available for download. Use --list-formats"))
        assertTrue(BotCheck.isBotCheck("ERROR: unable to download webpage: HTTP Error 429: Too Many Requests"))
        assertTrue(
            BotCheck.isBotCheck(
                "WARNING: [youtube] abc: formats require a GVS PO Token which was not provided\n" +
                    "ERROR: [youtube] abc: Requested format is not available"
            )
        )
    }

    @Test
    fun http403OnEveryFormat() {
        assertTrue(BotCheck.isBotCheck("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
    }

    @Test
    fun thisVideoIsUnavailable_isABotCheckUnlessItReallyIsGone() {
        assertTrue(BotCheck.isBotCheck("ERROR: [youtube] abc: Video unavailable. This video is unavailable"))
        assertFalse(BotCheck.isBotCheck("ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader"))
        assertFalse(
            BotCheck.isBotCheck(
                "ERROR: [youtube] abc: This video is unavailable. This video is no longer available because the " +
                    "YouTube account associated with this video has been terminated."
            )
        )
    }

    @Test
    fun theVideoItself_isNotABotCheck() {
        assertFalse(BotCheck.isBotCheck("ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users."))
        assertFalse(BotCheck.isBotCheck("ERROR: [youtube] abc: Private video. Sign in if you've been granted access to this video"))
        assertFalse(BotCheck.isBotCheck("ERROR: [youtube] abc: Join this channel to get access to members-only content like this video"))
        assertFalse(
            BotCheck.isBotCheck(
                "ERROR: [youtube] abc: Video unavailable. The uploader has not made this video available in your country"
            )
        )
        assertFalse(BotCheck.isBotCheck("ERROR: Unsupported URL: https://example.com/"))
        assertFalse(BotCheck.isBotCheck("ERROR: [generic] Unable to download webpage: Failed to resolve 'x.com'"))
        assertFalse(BotCheck.isBotCheck(""))
        assertFalse(BotCheck.isBotCheck(null))
    }
}
