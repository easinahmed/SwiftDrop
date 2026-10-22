package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ErrorMessagesTest {

    private fun readable(error: String) = ErrorMessages.readable("WARNING: [youtube] noise\n$error")

    @Test
    fun privateVideo() {
        assertEquals(ErrorMessages.PRIVATE, readable("ERROR: [youtube] abc: Private video. Sign in if you've been granted access to this video"))
    }

    @Test
    fun ageRestricted_suggestsSigningIn() {
        val message = readable("ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users.")
        assertEquals(ErrorMessages.AGE_RESTRICTED, message)
        assertTrue("Sign in to YouTube in Settings" in message)
    }

    @Test
    fun membersOnly() {
        assertEquals(
            ErrorMessages.MEMBERS_ONLY,
            readable("ERROR: [youtube] abc: Join this channel to get access to members-only content like this video, and other exclusive perks."),
        )
    }

    @Test
    fun notAvailableInYourCountry() {
        assertEquals(
            ErrorMessages.GEO_BLOCKED,
            readable("ERROR: [youtube] abc: Video unavailable. The uploader has not made this video available in your country"),
        )
        assertEquals(
            ErrorMessages.GEO_BLOCKED,
            readable("ERROR: [Bilibili] 123: This video is not available in your country due to geo restriction"),
        )
    }

    @Test
    fun botCheck_tellsTheUserWhatToDo() {
        val message = readable("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies-from-browser")
        assertEquals("YouTube is blocking downloads from this network. Try Wi-Fi, or sign in to YouTube in Settings.", message)
    }

    @Test
    fun otherCommonErrors() {
        assertEquals(ErrorMessages.UNSUPPORTED, readable("ERROR: Unsupported URL: https://example.com/"))
        assertEquals(ErrorMessages.NOT_FOUND, readable("ERROR: unable to download video data: HTTP Error 404: Not Found"))
        assertEquals(ErrorMessages.FORBIDDEN, readable("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
        assertEquals(
            ErrorMessages.NETWORK,
            readable("ERROR: [generic] Unable to download webpage: <urlopen error [Errno 7] No address associated with hostname>"),
        )
        assertEquals(ErrorMessages.NOT_STARTED, readable("ERROR: [youtube] abc: This live event will begin in 3 hours."))
        assertEquals(ErrorMessages.UNAVAILABLE, readable("ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader"))
    }

    @Test
    fun unknownErrors_keepYtDlpsText_withoutPrefixes() {
        assertEquals("Something odd happened", ErrorMessages.readable("ERROR: [vimeo] 12345678: Something odd happened"))
        assertEquals(ErrorMessages.GENERIC, ErrorMessages.readable(""))
        assertEquals(ErrorMessages.GENERIC, ErrorMessages.readable(null))
    }

    @Test
    fun cobaltCodes() {
        assertEquals(ErrorMessages.AGE_RESTRICTED, ErrorMessages.fromCobaltCode("error.api.content.video.age"))
        assertEquals(ErrorMessages.PRIVATE, ErrorMessages.fromCobaltCode("error.api.content.video.private"))
        assertEquals(ErrorMessages.GEO_BLOCKED, ErrorMessages.fromCobaltCode("error.api.content.video.region"))
        assertEquals(ErrorMessages.UNAVAILABLE, ErrorMessages.fromCobaltCode("error.api.content.video.unavailable"))
        assertNull(ErrorMessages.fromCobaltCode("error.api.youtube.login"))
        assertNull(ErrorMessages.fromCobaltCode(null))
    }
}
