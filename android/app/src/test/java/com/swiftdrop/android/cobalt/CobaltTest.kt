package com.swiftdrop.android.cobalt

import com.swiftdrop.android.core.AudioFormat
import com.swiftdrop.android.core.FormatOptions
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.VideoFormat
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CobaltTest {

    private val url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    private fun body(quality: Quality, options: FormatOptions = FormatOptions()) =
        JSONObject(CobaltRequest.build(url, quality, options).toJson())

    // -- Request builder ---------------------------------------------------------------------------

    @Test
    fun video_usesQualityCappedAt1080_andH264Mp4ByDefault() {
        val json = body(Quality.P720)
        assertEquals(url, json.getString("url"))
        assertEquals("720", json.getString("videoQuality"))
        assertEquals("h264", json.getString("youtubeVideoCodec"))
        assertEquals("mp4", json.getString("youtubeVideoContainer"))
        assertFalse(json.has("downloadMode"))
        assertEquals("1080", body(Quality.BEST).getString("videoQuality"))
        assertEquals("1080", body(Quality.P2160).getString("videoQuality"))
        assertEquals("1080", body(Quality.P1440).getString("videoQuality"))
        assertEquals("360", body(Quality.P360).getString("videoQuality"))
    }

    @Test
    fun video_followsFormatAndCodecSettings() {
        val webm = body(Quality.P1080, FormatOptions(videoFormat = VideoFormat.WEBM))
        assertEquals("webm", webm.getString("youtubeVideoContainer"))
        assertEquals("vp9", webm.getString("youtubeVideoCodec"))
        val mkv = body(Quality.P1080, FormatOptions(videoFormat = VideoFormat.MKV, preferH264 = false))
        assertEquals("mkv", mkv.getString("youtubeVideoContainer"))
        assertEquals("vp9", mkv.getString("youtubeVideoCodec"))
        val mkvH264 = body(Quality.P1080, FormatOptions(videoFormat = VideoFormat.MKV, preferH264 = true))
        assertEquals("h264", mkvH264.getString("youtubeVideoCodec"))
    }

    @Test
    fun audio_m4a_asksForBestWithH264_becauseCobaltHasNoM4a() {
        val json = body(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.M4A))
        assertEquals("audio", json.getString("downloadMode"))
        assertEquals("best", json.getString("audioFormat"))
        assertEquals("h264", json.getString("youtubeVideoCodec"))
        assertFalse(json.has("audioBitrate"))
        assertFalse(json.has("videoQuality"))
    }

    @Test
    fun audio_mp3_mapsBitrateToOneCobaltAccepts() {
        fun bitrate(kbps: Int) = body(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.MP3, mp3Bitrate = kbps))
        assertEquals("mp3", bitrate(192).getString("audioFormat"))
        assertEquals("128", bitrate(128).getString("audioBitrate"))
        assertEquals("256", bitrate(192).getString("audioBitrate")) // cobalt has no 192
        assertEquals("320", bitrate(320).getString("audioBitrate"))
    }

    @Test
    fun audio_opus() {
        val json = body(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.OPUS))
        assertEquals("opus", json.getString("audioFormat"))
        assertEquals("vp9", json.getString("youtubeVideoCodec"))
    }

    // -- Response parser ---------------------------------------------------------------------------

    @Test
    fun parse_tunnel() {
        val response = CobaltResponse.parse(
            """{"status":"tunnel","url":"https://rue-cobalt.xenon.zone/tunnel?id=abc&exp=1","filename":"Me at the zoo - jawed (240p, h264).mp4"}"""
        )
        assertEquals(
            CobaltResponse.Download("https://rue-cobalt.xenon.zone/tunnel?id=abc&exp=1", "Me at the zoo - jawed (240p, h264).mp4", tunnel = true),
            response,
        )
        assertEquals("https://rue-cobalt.xenon.zone/tunnel?id=abc&exp=1" to "Me at the zoo - jawed (240p, h264).mp4", response.mediaUrl(audioOnly = false))
    }

    @Test
    fun parse_redirect() {
        val response = CobaltResponse.parse("""{"status":"redirect","url":"https://cdn.example/v.mp4","filename":"v.mp4"}""")
        assertEquals(CobaltResponse.Download("https://cdn.example/v.mp4", "v.mp4", tunnel = false), response)
    }

    @Test
    fun parse_picker_takesFirstVideo_orTheAudioForAudioOnly() {
        val response = CobaltResponse.parse(
            """{"status":"picker","audio":"https://a/x.mp3","audioFilename":"x.mp3","picker":[
                {"type":"photo","url":"https://p/1.jpg"},{"type":"video","url":"https://v/2.mp4","thumb":"t"}]}"""
        )
        assertTrue(response is CobaltResponse.Picker)
        assertEquals(2, (response as CobaltResponse.Picker).items.size)
        assertEquals("https://v/2.mp4" to null, response.mediaUrl(audioOnly = false))
        assertEquals("https://a/x.mp3" to "x.mp3", response.mediaUrl(audioOnly = true))
    }

    @Test
    fun parse_errors() {
        val login = CobaltResponse.parse("""{"status":"error","error":{"code":"error.api.youtube.login"}}""")
        assertEquals(CobaltResponse.Error("error.api.youtube.login"), login)
        assertTrue(CobaltErrors.isLoginBlocked((login as CobaltResponse.Error).code))
        assertTrue(CobaltErrors.needsKey("error.api.auth.jwt.missing"))
        assertFalse(CobaltErrors.isLoginBlocked("error.api.content.video.unavailable"))
        assertNull(login.mediaUrl(audioOnly = false))
        assertEquals(CobaltResponse.Error(CobaltResponse.MALFORMED), CobaltResponse.parse("<html>502</html>"))
        assertEquals(CobaltResponse.Error(CobaltResponse.MALFORMED), CobaltResponse.parse("""{"status":"tunnel"}"""))
        assertEquals(CobaltResponse.Error(CobaltResponse.MALFORMED), CobaltResponse.parse(null))
        assertEquals(CobaltResponse.Unsupported("local-processing"), CobaltResponse.parse("""{"status":"local-processing"}"""))
    }

    @Test
    fun names_dropCobaltsQualityNote() {
        assertEquals("Me at the zoo - jawed", CobaltNames.title("Me at the zoo - jawed (240p, h264).mp4"))
        assertEquals("Me at the zoo - jawed", CobaltNames.title("Me at the zoo - jawed.m4a"))
        assertEquals("Song (Live)", CobaltNames.title("Song (Live).opus"))
        assertNull(CobaltNames.title(null))
        assertEquals("mp4", CobaltNames.extension("a (720p, h264).mp4"))
        assertNull(CobaltNames.extension("noextension"))
    }

    @Test
    fun instances_startWithTheWorkingServer() {
        assertEquals("https://rue-cobalt.xenon.zone/", CobaltInstances.DEFAULT.first())
    }
}
