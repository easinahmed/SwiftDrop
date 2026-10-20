package com.swiftdrop.android.spotify

import com.swiftdrop.android.core.EngineOutput
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SongStateTest {

    private val track = SpotifyTrack("6OmhkSOpvYBokMKQxpIGx2", "Global Warming (feat. Sensato)", listOf("Pitbull", "Sensato"), 85.4)

    @Test
    fun fileName_isArtistsThenTitle() {
        assertEquals("Pitbull, Sensato - Global Warming (feat. Sensato).m4a", track.fileName("m4a"))
        assertEquals("Rick Astley - Never Gonna Give You Up.m4a",
            SpotifyTrack("x", "Never Gonna Give You Up", listOf("Rick Astley"), 213.0).fileName("m4a"))
        assertEquals("AC DC - Back In Black.m4a", SpotifyTrack("x", "Back In Black", listOf("AC/DC"), 255.0).fileName("m4a"))
        assertEquals("What Is This.m4a", SpotifyTrack("x", "What Is This?", emptyList(), 1.0).fileName("M4A"))
    }

    @Test
    fun songState_roundTripsWithAndWithoutAMatch() {
        val plain = SongState(track)
        assertEquals(plain, SongState.fromJson(plain.toJson()))
        val matched = SongState(
            track.copy(image = "https://i.scdn.co/image/x"),
            Candidate("dQw4w9WgXcQ", "Global Warming", 86.0, listOf("Pitbull"), "Pitbull", music = true, album = "Global Warming"),
        )
        assertEquals(matched, SongState.fromJson(matched.toJson()))
        val noLength = SongState(track.copy(duration = null), Candidate("v", "t", null))
        assertEquals(noLength, SongState.fromJson(noLength.toJson()))
        assertNull(SongState.fromJson(null))
        assertNull(SongState.fromJson("{broken"))
    }

    @Test
    fun searchResults_readFlatEntries() {
        val music = """{"_type":"playlist","entries":[{"id":"a1","title":"expectations","duration":null},
            {"title":"no id"},{"id":"b2","title":"happier"}]}"""
        assertEquals(
            listOf(Candidate("a1", "expectations", null, music = true), Candidate("b2", "happier", null, music = true)),
            YtDlpResults.searchResults(music, music = true),
        )
        val videos = """{"entries":[{"id":"v1","title":"Olivia Rodrigo - expectations","duration":224.0,"channel":"Olivia Rodrigo"},
            {"id":"v2","title":"Lyrics","duration":225,"channel":null,"uploader":"Vibe Music"}]}"""
        assertEquals(
            listOf(
                Candidate("v1", "Olivia Rodrigo - expectations", 224.0, channel = "Olivia Rodrigo"),
                Candidate("v2", "Lyrics", 225.0, channel = "Vibe Music"),
            ),
            YtDlpResults.searchResults(videos, music = false),
        )
        assertEquals(emptyList<Candidate>(), YtDlpResults.searchResults("{}", music = false))
    }

    @Test
    fun details_preferTrackNameAndArtists() {
        val json = """{"id":"song","title":"expectations (Official Audio)","track":"expectations","duration":224,
            "artists":["Olivia Rodrigo","Chappell Roan"],"channel":"Olivia Rodrigo","album":"GUTS"}"""
        assertEquals(
            Candidate("song", "expectations", 224.0, listOf("Olivia Rodrigo", "Chappell Roan"), "Olivia Rodrigo", music = true, album = "GUTS"),
            YtDlpResults.details(json, "song"),
        )
        val creators = """{"title":"Song","duration":100.5,"creators":["Band"]}"""
        assertEquals(Candidate("x", "Song", 100.5, listOf("Band"), "", music = true), YtDlpResults.details(creators, "x"))
    }

    @Test
    fun songTags_replaceTheYouTubeNames() {
        val info = """{"id":"v","title":"Pitbull - Global Warming ft. Sensato (Official Video) [4K]","artist":"Pitbull",
            "artists":["Pitbull"],"formats":[{"format_id":"140"}]}"""
        val tagged = JSONObject(YtDlpResults.withSongTags(info, track, "Global Warming"))
        assertEquals("Global Warming (feat. Sensato)", tagged.getString("track"))
        assertEquals("Pitbull, Sensato", tagged.getString("artist"))
        assertEquals(2, tagged.getJSONArray("artists").length())
        assertEquals("Global Warming", tagged.getString("album"))
        assertEquals("140", tagged.getJSONArray("formats").getJSONObject(0).getString("format_id")) // the rest is kept
        assertFalse(JSONObject(YtDlpResults.withSongTags(info, track, null)).has("album"))
    }

    // -- one retry on HTTP 403 -------------------------------------------------------------------

    private class EngineError(message: String) : Exception(message)

    private val forbidden = { e: Throwable -> EngineOutput.isForbidden(e.message) }

    @Test
    fun aRefusedStream_isTriedOnceMore() = runBlocking {
        var calls = 0
        val result = retryOnceWhen(forbidden) {
            calls++
            if (calls == 1) throw EngineError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
            "saved"
        }
        assertEquals("saved", result)
        assertEquals(2, calls)
    }

    @Test
    fun aStreamRefusedTwice_fails() = runBlocking {
        var calls = 0
        val error = runCatching {
            retryOnceWhen(forbidden) {
                calls++
                throw EngineError("HTTP Error 403: Forbidden")
            }
        }.exceptionOrNull()
        assertTrue(error is EngineError)
        assertEquals(2, calls)
    }

    @Test
    fun otherErrors_areNotRetried() = runBlocking {
        var calls = 0
        runCatching {
            retryOnceWhen(forbidden) {
                calls++
                throw EngineError("ERROR: [youtube] v: Private video")
            }
        }
        assertEquals(1, calls)
        assertFalse(EngineOutput.isForbidden(null))
    }
}
