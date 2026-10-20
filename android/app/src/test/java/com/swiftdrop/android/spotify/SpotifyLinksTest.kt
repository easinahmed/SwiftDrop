package com.swiftdrop.android.spotify

import com.swiftdrop.android.core.LinkExtractor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class SpotifyLinksTest {

    private val playlistId = "37i9dQZF1DXcBWIGoYBM5M"
    private val trackId = "4cOdK2wGLETKBW3PvgPWqT"
    private val trackUrl = "https://open.spotify.com/track/$trackId"

    @Test
    fun parse_acceptsSongsAlbumsAndPlaylists() {
        val cases = mapOf(
            "https://open.spotify.com/playlist/$playlistId?si=abc123" to SpotifyLink("playlist", playlistId),
            "https://open.spotify.com/intl-de/track/$trackId" to SpotifyLink("track", trackId),
            "https://open.spotify.com/intl-pt-BR/track/$trackId" to SpotifyLink("track", trackId),
            "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy" to SpotifyLink("album", "4aawyAB9vmqN3uQ7FjRGTy"),
            "https://open.spotify.com/embed/track/$trackId" to SpotifyLink("track", trackId),
            "https://play.spotify.com/track/$trackId" to SpotifyLink("track", trackId),
            "https://open.spotify.com/track/$trackId/" to SpotifyLink("track", trackId),
            "https://open.spotify.com/TRACK/$trackId#x" to SpotifyLink("track", trackId),
        )
        for ((url, expected) in cases) assertEquals(url, expected, SpotifyLinks.parse(url))
    }

    @Test
    fun parse_refusesEverythingElse() {
        listOf(
            "https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf",
            "https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0",
            "https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt",
            "https://example.com/track/$trackId",
            "https://open.spotify.com/track/tooShort",
            "https://open.spotify.com/track/$trackId/../../x",
            "https://open.spotify.com/",
            "https://spotify.link/zLIDHxA0bKb",
        ).forEach { assertNull(it, SpotifyLinks.parse(it)) }
    }

    @Test
    fun links_areCanonical() {
        assertEquals(trackUrl, SpotifyLink("track", trackId).url)
        assertEquals("https://open.spotify.com/embed/track/$trackId", SpotifyLink("track", trackId).embedUrl)
    }

    @Test
    fun sharedText_givesAParsableLinkWithoutTracking() {
        val shared = "Listen to Road Trip on Spotify: https://open.spotify.com/playlist/$playlistId?si=f00ba4&pi=x"
        val url = LinkExtractor.firstUrl(shared)!!
        assertEquals("https://open.spotify.com/playlist/$playlistId?pi=x", url)
        assertEquals(SpotifyLink("playlist", playlistId), SpotifyLinks.parse(url))
    }

    @Test
    fun shortLinks_areRecognised() {
        assertTrue(SpotifyLinks.isShortLink("https://spotify.link/zLIDHxA0bKb"))
        assertTrue(SpotifyLinks.isShortLink("https://spotify.app.link/zLIDHxA0bKb?_p=c1"))
        assertFalse(SpotifyLinks.isShortLink("https://notspotify.link/x"))
        assertFalse(SpotifyLinks.isShortLink(trackUrl))
    }

    @Test
    fun isSpotify_coversEverySpotifyHost() {
        assertTrue(SpotifyLinks.isSpotify(trackUrl))
        assertTrue(SpotifyLinks.isSpotify("https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf"))
        assertTrue(SpotifyLinks.isSpotify("https://spotify.link/zLIDHxA0bKb"))
        assertFalse(SpotifyLinks.isSpotify("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        assertFalse(SpotifyLinks.isSpotify("https://spotify.com.evil.example/track/$trackId"))
    }

    @Test
    fun refusal_explainsPodcastsAndOtherPages() {
        val podcast = SpotifyLinks.refusal("https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf")
        assertNotNull(podcast)
        assertTrue(podcast!!.contains("podcasts", ignoreCase = true))
        assertTrue(SpotifyLinks.refusal("https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0")!!.contains("podcasts"))
        val artist = SpotifyLinks.refusal("https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt")
        assertTrue(artist!!.startsWith("Unsupported Spotify link"))
        assertNull(SpotifyLinks.refusal(trackUrl))
        assertNull(SpotifyLinks.refusal("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"))
        assertNull(SpotifyLinks.refusal("https://spotify.link/zLIDHxA0bKb")) // decided once resolved
        assertNull(SpotifyLinks.refusal("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    }

    // -- short links -----------------------------------------------------------------------

    private val short = "https://spotify.link/zLIDHxA0bKb"

    private fun pages(vararg answers: Pair<String, SpotifyLinks.Answer>): (String) -> SpotifyLinks.Answer {
        val map = answers.toMap()
        return { url -> map[url] ?: throw AssertionError("unexpected fetch of $url") }
    }

    @Test
    fun shortLink_followsRedirectsToTheTarget() {
        val fetch = pages(
            short to SpotifyLinks.Answer(307, "https://spotify.app.link/zLIDHxA0bKb?_p=c1", ""),
            "https://spotify.app.link/zLIDHxA0bKb?_p=c1" to
                SpotifyLinks.Answer(307, "https://open.spotify.com/playlist/$playlistId?si=x&_branch_match_id=1", ""),
        )
        assertEquals(SpotifyLink("playlist", playlistId), SpotifyLinks.resolve(short, fetch))
    }

    @Test
    fun shortLink_readsBranchsInBetweenPage() {
        val fetch = pages(short to SpotifyLinks.Answer(200, null, """<a href="$trackUrl">Open</a>"""))
        assertEquals(SpotifyLink("track", trackId), SpotifyLinks.resolve(short, fetch))
    }

    @Test
    fun shortLink_resolvesRelativeRedirects() {
        val fetch = pages(
            short to SpotifyLinks.Answer(302, "/zLIDHxA0bKb?step=2", ""),
            "https://spotify.link/zLIDHxA0bKb?step=2" to SpotifyLinks.Answer(301, "$trackUrl?si=1", ""),
        )
        assertEquals(SpotifyLink("track", trackId), SpotifyLinks.resolve(short, fetch))
    }

    @Test
    fun deadShortLink_neverPicksAPlaylistFromTheHomePage() {
        // A dead link lands on https://open.spotify.com/, whose page links to featured playlists.
        // It must fail without reading that page.
        val fetch = pages(short to SpotifyLinks.Answer(307, "https://open.spotify.com/", ""))
        val error = expectFailure { SpotifyLinks.resolve(short, fetch) }
        assertEquals(SpotifyException.Reason.UNSUPPORTED, error.reason)
        assertTrue(error.message!!.startsWith("Unsupported Spotify link"))
    }

    @Test
    fun shortLink_toAPodcast_isRefused() {
        val fetch = pages(short to SpotifyLinks.Answer(307, "https://open.spotify.com/episode/0Q86acNRm6V9GYx55SXKwf", ""))
        val error = expectFailure { SpotifyLinks.resolve(short, fetch) }
        assertTrue(error.message!!.contains("podcasts"))
    }

    @Test
    fun shortLink_inBetweenPageWithoutALink_isUnsupported() {
        val fetch = pages(short to SpotifyLinks.Answer(200, null, "<html>nothing here</html>"))
        assertEquals(SpotifyException.Reason.UNSUPPORTED, expectFailure { SpotifyLinks.resolve(short, fetch) }.reason)
    }

    @Test
    fun shortLink_httpErrors_areReported() {
        val fetch = pages(short to SpotifyLinks.Answer(404, null, ""))
        assertEquals(SpotifyException.Reason.NOT_FOUND, expectFailure { SpotifyLinks.resolve(short, fetch) }.reason)
    }

    @Test
    fun directLinks_needNoFetch() {
        assertEquals(SpotifyLink("track", trackId), SpotifyLinks.resolve("$trackUrl?si=abc") { fail(); throw AssertionError() })
    }

    private fun expectFailure(block: () -> Unit): SpotifyException {
        try {
            block()
        } catch (e: SpotifyException) {
            return e
        }
        throw AssertionError("expected a SpotifyException")
    }
}
