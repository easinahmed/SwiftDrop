package com.swiftdrop.android.spotify

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ported from the desktop tests/test_spotify.py matching cases. */
class SongMatchTest {

    private val expectations = SpotifyTrack(
        "x", "expectations (feat. Chappell Roan)", listOf("Olivia Rodrigo", "Chappell Roan"), 223.935,
    )

    private fun video(title: String, duration: Double?, channel: String = "", artists: List<String> = emptyList()) =
        Candidate(videoId = "v", title = title, duration = duration, channel = channel, artists = artists)

    @Test
    fun officialAudio_matches() {
        assertNotNull(SongMatch.score(expectations, video("expectations", 224.0, "Olivia Rodrigo", listOf("Olivia Rodrigo"))))
    }

    @Test
    fun lyricVideoWithTheSameLength_matches() {
        assertNotNull(SongMatch.score(expectations, video("Olivia Rodrigo, Chappell Roan - expectations (Lyric Video)", 225.0)))
    }

    @Test
    fun lengthMismatch_isRejected() {
        val musicVideo = video("Olivia Rodrigo - expectations (feat. Chappell Roan) (Official Music Video)", 293.0)
        assertNull(SongMatch.score(expectations, musicVideo))
    }

    @Test
    fun lengthWindow_isFourSecondsOrThreePercent() {
        val short = SpotifyTrack("x", "Short", listOf("Band"), 100.0) // 3 % = 3 s, so 4 s
        assertNotNull(SongMatch.score(short, video("Band - Short", 104.0)))
        assertNull(SongMatch.score(short, video("Band - Short", 104.1)))
        val long = SpotifyTrack("x", "Epic", listOf("Band"), 600.0) // 3 % = 18 s
        assertNotNull(SongMatch.score(long, video("Band - Epic", 617.0)))
        assertNull(SongMatch.score(long, video("Band - Epic", 619.0)))
    }

    @Test
    fun noLength_isRejected() {
        assertNull(SongMatch.score(expectations, video("Olivia Rodrigo - expectations", null)))
    }

    @Test
    fun otherVersions_areRejected() {
        listOf(
            "Olivia Rodrigo - expectations (Live at Glastonbury)",
            "Olivia Rodrigo - expectations (Remix)",
            "expectations - Olivia Rodrigo (Karaoke Version)",
            "Olivia Rodrigo - expectations (sped up)",
            "Producer Reacts to Olivia Rodrigo || Expectations",
        ).forEach { assertNull(it, SongMatch.score(expectations, video(it, 224.0))) }
    }

    @Test
    fun aLiveSong_mayMatchALiveVersion() {
        val live = SpotifyTrack("x", "Yellow - Live in Buenos Aires", listOf("Coldplay"), 300.0)
        assertNotNull(SongMatch.score(live, video("Coldplay - Yellow (Live In Buenos Aires)", 301.0)))
    }

    @Test
    fun aRemixOnSpotify_matchesTheRemix() {
        // The version check uses the full Spotify title, not the core title.
        val remix = SpotifyTrack("x", "Spend Dat (feat. Someone) - Remix", listOf("Rapper"), 200.0)
        assertNotNull(SongMatch.score(remix, Candidate("v", "Spend Dat (Remix)", 201.0, listOf("Rapper"), music = true)))
    }

    @Test
    fun wrongArtist_isRejected() {
        assertNull(SongMatch.score(expectations, video("Someone Else - expectations", 224.0, "Someone Else")))
    }

    @Test
    fun wrongTitle_isRejected() {
        assertNull(SongMatch.score(expectations, video("Olivia Rodrigo - happier", 224.0, "Olivia Rodrigo")))
    }

    @Test
    fun nonLatinTitles_match() {
        val song = SpotifyTrack("x", "আমার সোনার বাংলা", listOf("Rabindranath Tagore"), 180.0)
        assertNotNull(SongMatch.score(song, video("আমার সোনার বাংলা | Rabindranath Tagore", 182.0)))
    }

    @Test
    fun closerOfficialAudio_scoresHigher() {
        val official = Candidate("a", "expectations", 224.0, listOf("Olivia Rodrigo", "Chappell Roan"), "Olivia Rodrigo", music = true)
        val lyric = video("Olivia Rodrigo, Chappell Roan - Expectations (Lyrics)", 228.0, "Vibe Music")
        assertTrue(SongMatch.score(expectations, official)!! > SongMatch.score(expectations, lyric)!!)
    }

    @Test
    fun coreTitle_dropsFeaturingAndSuffixes() {
        assertEquals("expectations", SongMatch.coreTitle("expectations (feat. Chappell Roan)"))
        assertEquals("Yellow", SongMatch.coreTitle("Yellow - Live in Buenos Aires"))
        assertEquals("Song", SongMatch.coreTitle("Song [with Friend] - Remastered 2011"))
        assertEquals("Song", SongMatch.coreTitle("Song (ft. A, B)"))
    }

    @Test
    fun words_foldCaseAndWidth() {
        assertEquals(listOf("ss", "strasse"), SongMatch.words("SS Straße"))
        assertEquals(listOf("abc", "123"), SongMatch.words("ＡＢＣ　１２３")) // full-width, NFKC
        assertEquals(listOf("don", "t", "stop"), SongMatch.words("Don't Stop!"))
    }

    // -- matcher ------------------------------------------------------------------------------

    private open class FakeSearch(
        val musicResults: List<Candidate> = emptyList(),
        val detailsById: Map<String, Candidate> = emptyMap(),
        val videoResults: List<Candidate> = emptyList(),
    ) : SongSearch {
        val calls = mutableListOf<Pair<String, String>>()

        override suspend fun music(query: String): List<Candidate> {
            calls += "music" to query
            return musicResults
        }

        override suspend fun details(videoId: String): Candidate {
            calls += "details" to videoId
            return detailsById.getValue(videoId)
        }

        override suspend fun videos(query: String): List<Candidate> {
            calls += "videos" to query
            return videoResults
        }
    }

    @Test
    fun matcher_prefersYouTubeMusicAndChecksDetails() = runBlocking {
        val search = FakeSearch(
            musicResults = listOf(Candidate("wrong", "happier", null, music = true), Candidate("song", "expectations", null, music = true)),
            detailsById = mapOf("song" to Candidate("song", "expectations", 224.0, listOf("Olivia Rodrigo"), "Olivia Rodrigo", music = true)),
        )
        val match = SongMatcher(search).find(expectations)
        assertEquals("song", match?.videoId)
        assertFalse(("details" to "wrong") in search.calls) // titles that can't match aren't looked up
        assertFalse(search.calls.any { it.first == "videos" })
        assertEquals("music" to "Olivia Rodrigo Chappell Roan expectations", search.calls.first())
    }

    @Test
    fun matcher_looksUpAtMostThreeYouTubeMusicResults() = runBlocking {
        val results = (1..5).map { Candidate("m$it", "expectations", null, music = true) }
        val search = FakeSearch(
            musicResults = results,
            detailsById = results.associate { it.videoId to it.copy(duration = 300.0) }, // all the wrong length
        )
        assertNull(SongMatcher(search).find(expectations))
        assertEquals(3, search.calls.count { it.first == "details" })
        assertEquals("videos" to "Olivia Rodrigo Chappell Roan - expectations", search.calls.last())
    }

    @Test
    fun matcher_fallsBackToYouTubeSearch() = runBlocking {
        val search = FakeSearch(
            musicResults = listOf(Candidate("song", "expectations", null, music = true)),
            detailsById = mapOf("song" to Candidate("song", "expectations", 300.0, listOf("Olivia Rodrigo"), music = true)),
            videoResults = listOf(video("Olivia Rodrigo, Chappell Roan - expectations (Lyric Video)", 225.0)),
        )
        val match = SongMatcher(search).find(expectations)
        assertTrue(match!!.title.endsWith("(Lyric Video)"))
    }

    @Test
    fun matcher_takesTheBestScoringVideo() = runBlocking {
        val search = FakeSearch(
            videoResults = listOf(
                Candidate("far", "Olivia Rodrigo - expectations", 227.5, channel = "Fan"),
                Candidate("close", "Olivia Rodrigo - expectations", 224.0, channel = "Olivia Rodrigo"),
            ),
        )
        assertEquals("close", SongMatcher(search).find(expectations)?.videoId)
    }

    @Test
    fun matcher_returnsNullWithoutAGoodMatch() = runBlocking {
        val search = FakeSearch(videoResults = listOf(video("Olivia Rodrigo - expectations (Live)", 224.0)))
        assertNull(SongMatcher(search).find(expectations))
    }

    @Test
    fun matcher_survivesAFailedDetailLookupAndFailedSearches() = runBlocking {
        val flaky = object : FakeSearch(
            musicResults = listOf(Candidate("song", "expectations", null, music = true)),
            videoResults = listOf(video("Olivia Rodrigo - expectations (Official Audio)", 224.0, "Olivia Rodrigo")),
        ) {
            override suspend fun details(videoId: String): Candidate = throw IllegalStateException("connection reset")
        }
        assertNotNull(SongMatcher(flaky).find(expectations))

        val offline = object : FakeSearch() {
            override suspend fun music(query: String): List<Candidate> = throw IllegalStateException("offline")
            override suspend fun videos(query: String): List<Candidate> = throw IllegalStateException("offline")
        }
        assertNull(SongMatcher(offline).find(expectations))
    }
}
