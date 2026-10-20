package com.swiftdrop.android.spotify

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpotifyEmbedTest {

    private val playlist = SpotifyLink("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    private val trackLink = SpotifyLink("track", "4cOdK2wGLETKBW3PvgPWqT")

    private fun embedPage(pageProps: JSONObject): String {
        val data = JSONObject().put("props", JSONObject().put("pageProps", pageProps)).put("page", "/embed/[type]/[id]")
        return "<!DOCTYPE html><html><head></head><body>" +
            """<script id="__NEXT_DATA__" type="application/json">$data</script>""" +
            "</body></html>"
    }

    private fun entityPage(entity: JSONObject) =
        embedPage(JSONObject().put("state", JSONObject().put("data", JSONObject().put("entity", entity))))

    private fun trackItem(id: String, title: String, artists: String, ms: Int) = JSONObject()
        .put("uri", "spotify:track:$id").put("title", title).put("subtitle", artists).put("duration", ms)

    private fun playlistEntity(tracks: List<JSONObject>, kind: String = "playlist") = JSONObject()
        .put("type", kind)
        .put("name", "Road Trip")
        .put("title", "Road Trip")
        .put("subtitle", "Easin")
        .put("coverArt", JSONObject().put("sources", JSONArray().put(JSONObject().put("url", "https://i.scdn.co/image/cover"))))
        .put("trackList", JSONArray(tracks))

    private val songs = listOf(
        trackItem("6OmhkSOpvYBokMKQxpIGx2", "Global Warming (feat. Sensato)", "Pitbull, Sensato", 85400),
        trackItem("0000000000000000000002", "EARFQUAKE", "Tyler, The Creator", 190067),
        JSONObject().put("uri", "spotify:episode:0000000000000000000003").put("title", "A podcast")
            .put("subtitle", "Show").put("duration", 1),
        trackItem("0000000000000000000004", "আমার সোনার বাংলা", "Rabindranath Tagore", 180000),
    )

    private fun fixture(name: String): String =
        javaClass.classLoader!!.getResource("spotify/$name")!!.readText()

    @Test
    fun playlist_listsSongsWithArtistsAndLengths() {
        val collection = SpotifyEmbed.parse(entityPage(playlistEntity(songs)), playlist) as SpotifyCollection
        assertEquals("Road Trip", collection.name)
        assertEquals("https://i.scdn.co/image/cover", collection.image)
        // The podcast episode is left out.
        assertEquals(
            listOf("6OmhkSOpvYBokMKQxpIGx2", "0000000000000000000002", "0000000000000000000004"),
            collection.tracks.map { it.id },
        )
        val (first, tyler, bangla) = collection.tracks
        assertEquals(listOf("Pitbull", "Sensato"), first.artists)
        assertEquals(85.4, first.duration!!, 1e-9)
        assertEquals(listOf("Tyler, The Creator"), tyler.artists) // only ",<nbsp>" separates artists
        assertEquals("Rabindranath Tagore - আমার সোনার বাংলা", bangla.display)
        assertEquals("Pitbull, Sensato - Global Warming (feat. Sensato)", first.display)
        assertFalse(collection.partial)
    }

    @Test
    fun track_hasTitleArtistsLengthAndLargestImage() {
        val entity = JSONObject()
            .put("type", "track")
            .put("name", "Never Gonna Give You Up")
            .put("title", "Never Gonna Give You Up")
            .put("artists", JSONArray().put(JSONObject().put("name", "Rick Astley").put("uri", "spotify:artist:0gxyHStUsqpMadRV0Di1Qt")))
            .put("duration", 213573)
            .put("visualIdentity", JSONObject().put("image", JSONArray()
                .put(JSONObject().put("url", "https://image-cdn/small").put("maxWidth", 64))
                .put(JSONObject().put("url", "https://image-cdn/large").put("maxWidth", 640))))
        val track = SpotifyEmbed.parse(entityPage(entity), trackLink) as SpotifyTrack
        assertEquals(trackLink.id, track.id)
        assertEquals("Never Gonna Give You Up", track.title)
        assertEquals(listOf("Rick Astley"), track.artists)
        assertEquals(213.573, track.duration!!, 1e-9)
        assertEquals("https://image-cdn/large", track.image)
    }

    @Test
    fun missingPlaylist_isReportedAsNotFound() {
        val page = embedPage(JSONObject().put("status", 404).put("title", "Page not found"))
        val error = expectFailure { SpotifyEmbed.parse(page, playlist) }
        assertEquals(SpotifyException.Reason.NOT_FOUND, error.reason)
        assertTrue(error.message!!.contains("private"))
    }

    @Test
    fun changedPage_failsClearly() {
        val pages = listOf(
            "<html>no data here</html>",
            """<script id="__NEXT_DATA__" type="application/json">{not json</script>""",
            embedPage(JSONObject().put("state", JSONObject().put("data", JSONObject()))),
            entityPage(JSONObject().put("type", "playlist").put("name", "x").put("trackList", "nope")),
            entityPage(JSONObject().put("type", "track")), // a song without a title
        )
        for (page in pages) {
            val link = if (page.contains("\"track\"")) trackLink else playlist
            val error = expectFailure { SpotifyEmbed.parse(page, link) }
            assertEquals(page, SpotifyException.Reason.PAGE_CHANGED, error.reason)
            assertTrue(error.message!!.contains("Spotify"))
        }
    }

    @Test
    fun collectionName_isTrimmed() {
        val entity = playlistEntity(songs).put("name", "plastic memories ")
        assertEquals("plastic memories", (SpotifyEmbed.parse(entityPage(entity), playlist) as SpotifyCollection).name)
    }

    @Test
    fun hundredSongPlaylist_isMarkedPartial() {
        val tracks = (0 until 100).map { n -> trackItem("%022d".format(n), "Song $n", "Artist", 200000) }
        val list = SpotifyEmbed.parse(entityPage(playlistEntity(tracks)), playlist) as SpotifyCollection
        assertEquals(100, list.tracks.size)
        assertTrue(list.partial)
        val album = SpotifyEmbed.parse(entityPage(playlistEntity(tracks, "album")), SpotifyLink("album", playlist.id))
        assertFalse((album as SpotifyCollection).partial) // albums aren't capped
    }

    @Test
    fun realAlbumEmbedPage() {
        val link = SpotifyLink("album", "6N9PS4QXF1D0OWPk0Sxtb4")
        val album = SpotifyEmbed.parse(fixture("album_embed.html"), link) as SpotifyCollection
        assertEquals("album", album.kind)
        assertEquals("Whenever You Need Somebody", album.name)
        assertEquals(10, album.tracks.size)
        val first = album.tracks.first()
        assertEquals(SpotifyTrack("4uLU6hMCjMI75M1A2tKUQC", "Never Gonna Give You Up", listOf("Rick Astley"), 213.573), first)
        assertEquals("When I Fall in Love", album.tracks.last().title)
        assertTrue(album.image!!.endsWith("ab67616d0000b273255e131abc1410833be95673")) // the 640 px cover
        assertFalse(album.partial)
    }

    @Test
    fun realTrackEmbedPage() {
        val track = SpotifyEmbed.parse(fixture("track_embed.html"), trackLink) as SpotifyTrack
        assertEquals("Rick Astley - Never Gonna Give You Up", track.display)
        assertEquals(213.573, track.duration!!, 1e-9)
        assertTrue(track.image!!.endsWith("ab67616d0000b273baf89eb11ec7c657805d2da0"))
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
