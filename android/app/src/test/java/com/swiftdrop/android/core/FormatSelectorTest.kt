package com.swiftdrop.android.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FormatSelectorTest {

    @Test
    fun defaultQuality_is1080p() {
        assertEquals(Quality.P1080, Quality.DEFAULT)
        assertEquals(Quality.P1080, Quality.fromKey(null))
        assertEquals(Quality.P1080, Quality.fromKey("nonsense"))
        assertEquals(Quality.AUDIO, Quality.fromKey("AUDIO"))
    }

    @Test
    fun p1080_mergesBestVideoAndAudioPreferringH264Aac_fallsBackToSingleFile() {
        assertEquals(
            listOf(
                "-f", "bv*+ba/b",
                "-S", "res:1080,vcodec:h264,acodec:aac,ext:mp4:m4a",
                "--merge-output-format", "mp4",
            ),
            FormatSelector.args(Quality.P1080),
        )
    }

    @Test
    fun p720_and_p480_capResolution() {
        assertEquals("res:720,vcodec:h264,acodec:aac,ext:mp4:m4a", FormatSelector.plan(Quality.P720).sort)
        assertEquals("res:480,vcodec:h264,acodec:aac,ext:mp4:m4a", FormatSelector.plan(Quality.P480).sort)
        assertEquals("bv*+ba/b", FormatSelector.plan(Quality.P720).format)
        assertEquals("bv*+ba/b", FormatSelector.plan(Quality.P480).format)
    }

    @Test
    fun best_hasNoResolutionCap() {
        val plan = FormatSelector.plan(Quality.BEST)
        assertEquals("bv*+ba/b", plan.format)
        assertEquals("res,vcodec:h264,acodec:aac,ext:mp4:m4a", plan.sort)
        assertEquals(listOf("--merge-output-format", "mp4"), plan.postProcessing)
    }

    @Test
    fun everyVideoQuality_endsWithSingleFileFallback() {
        Quality.entries.filter { !it.isAudio }.forEach { quality ->
            assertTrue(quality.name, FormatSelector.plan(quality).format.endsWith("/b"))
            assertTrue(quality.name, FormatSelector.args(quality).containsAll(listOf("--merge-output-format", "mp4")))
        }
    }

    @Test
    fun audioOnly_extractsM4a() {
        val args = FormatSelector.args(Quality.AUDIO)
        assertEquals(
            listOf(
                "-f", "ba[ext=m4a]/ba[acodec^=mp4a]/ba/b",
                "-S", "acodec:aac,ext:m4a",
                "-x", "--audio-format", "m4a",
            ),
            args,
        )
        assertFalse(args.contains("--merge-output-format"))
    }

    @Test
    fun newQualities_capResolution() {
        assertEquals("res:2160,vcodec:h264,acodec:aac,ext:mp4:m4a", FormatSelector.plan(Quality.P2160).sort)
        assertEquals("res:1440,vcodec:h264,acodec:aac,ext:mp4:m4a", FormatSelector.plan(Quality.P1440).sort)
        assertEquals("res:360,vcodec:h264,acodec:aac,ext:mp4:m4a", FormatSelector.plan(Quality.P360).sort)
    }

    @Test
    fun h264Off_letsTheBestCodecWin() {
        val plan = FormatSelector.plan(Quality.P1080, FormatOptions(preferH264 = false))
        assertEquals("res:1080", plan.sort)
        assertEquals(listOf("--merge-output-format", "mp4"), plan.postProcessing)
    }

    @Test
    fun mkv_mergesAndRemuxesIntoMkv() {
        val plan = FormatSelector.plan(Quality.P720, FormatOptions(videoFormat = VideoFormat.MKV))
        assertEquals("res:720,vcodec:h264,acodec:aac", plan.sort)
        assertEquals(listOf("--merge-output-format", "mkv", "--remux-video", "mkv"), plan.postProcessing)
    }

    @Test
    fun webm_prefersVp9Opus_andFallsBackToMkv() {
        val plan = FormatSelector.plan(Quality.BEST, FormatOptions(videoFormat = VideoFormat.WEBM, preferH264 = true))
        assertEquals("res,vcodec:vp9,acodec:opus,ext:webm:webm", plan.sort)
        assertEquals(listOf("--merge-output-format", "webm/mkv"), plan.postProcessing)
    }

    @Test
    fun audioMp3_convertsAtTheChosenBitrate() {
        assertEquals(
            listOf("-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "320K"),
            FormatSelector.args(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.MP3, mp3Bitrate = 320)),
        )
        assertEquals(
            "192K",
            FormatSelector.args(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.MP3, mp3Bitrate = 7)).last(),
        )
    }

    @Test
    fun audioOpus_prefersOpusStreams() {
        assertEquals(
            listOf("-f", "ba[acodec=opus]/ba/b", "-S", "acodec:opus", "-x", "--audio-format", "opus"),
            FormatSelector.args(Quality.AUDIO, FormatOptions(audioFormat = AudioFormat.OPUS)),
        )
    }

    @Test
    fun oldQualityNames_stillResolve() {
        listOf("BEST", "P1080", "P720", "P480", "AUDIO").forEach { assertEquals(it, Quality.fromKey(it).name) }
    }
}
