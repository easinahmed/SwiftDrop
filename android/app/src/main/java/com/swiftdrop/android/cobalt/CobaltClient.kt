package com.swiftdrop.android.cobalt

import android.util.Log
import com.swiftdrop.android.core.ErrorMessages
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Fetches one YouTube video through cobalt when YouTube refuses yt-dlp on this network: asks each
 * server in turn for a download link, then streams the file into [workDir]. Blocking: call it
 * from a background thread (interrupting the thread stops the transfer).
 */
class CobaltClient(
    private val instances: List<String> = CobaltInstances.DEFAULT,
    private val userAgent: String = "SwiftDrop-Android",
) {

    sealed interface Outcome {
        data class Saved(val file: File, val filename: String?, val instance: String) : Outcome
        data class Failed(val message: String) : Outcome
    }

    fun interface Progress {
        fun onBytes(downloaded: Long, total: Long?)
    }

    fun download(request: CobaltRequest, workDir: File, progress: Progress): Outcome {
        var videoProblem: String? = null
        for ((index, instance) in instances.withIndex()) {
            checkInterrupted()
            val answer = try {
                ask(instance, request)
            } catch (e: IOException) {
                Log.w(TAG, "cobalt ${host(instance)} unreachable: ${e.javaClass.simpleName}")
                continue
            }
            if (answer is CobaltResponse.Error) {
                Log.i(TAG, "cobalt ${host(instance)} answered ${answer.code}")
                // A server blocked by YouTube itself (youtube.login) or wanting a key is skipped;
                // an answer about the video is remembered in case no server can fetch it.
                if (!CobaltErrors.isLoginBlocked(answer.code) && !CobaltErrors.needsKey(answer.code)) {
                    videoProblem = videoProblem ?: ErrorMessages.fromCobaltCode(answer.code)
                }
                continue
            }
            val (mediaUrl, filename) = answer.mediaUrl(request.audioOnly) ?: run {
                Log.i(TAG, "cobalt ${host(instance)} gave nothing to download ($answer)")
                null
            } ?: continue
            val ext = CobaltNames.extension(filename) ?: if (request.audioOnly) "m4a" else request.videoContainer
            val target = File(workDir, "cobalt-$index.$ext")
            try {
                fetch(mediaUrl, target, progress)
            } catch (e: IOException) {
                Log.w(TAG, "cobalt ${host(instance)} transfer failed: ${e.javaClass.simpleName}")
                target.delete()
                continue
            }
            if (target.length() > 0) return Outcome.Saved(target, filename, host(instance))
            target.delete()
        }
        return Outcome.Failed(videoProblem ?: ErrorMessages.BOT_CHECK)
    }

    private fun ask(instance: String, request: CobaltRequest): CobaltResponse {
        val connection = URL(instance).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.doOutput = true
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("User-Agent", userAgent)
            connection.outputStream.use { it.write(request.toJson().toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream: InputStream? = if (code >= 400) connection.errorStream else connection.inputStream
            val body = stream?.use { String(it.readBytes(), Charsets.UTF_8) }
            if (body.isNullOrBlank()) return CobaltResponse.Error("error.swiftdrop.http_$code")
            return CobaltResponse.parse(body)
        } finally {
            connection.disconnect()
        }
    }

    /** Streams [url] into [target]; tunnels give only an estimated length, which is enough for progress. */
    private fun fetch(url: String, target: File, progress: Progress) {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = true
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.setRequestProperty("User-Agent", userAgent)
            val code = connection.responseCode
            if (code !in 200..299) throw IOException("HTTP $code")
            val total = connection.contentLengthLong.takeIf { it > 0 }
                ?: connection.getHeaderField("Estimated-Content-Length")?.toLongOrNull()?.takeIf { it > 0 }
            var downloaded = 0L
            var lastReport = 0L
            connection.inputStream.use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(BUFFER)
                    while (true) {
                        checkInterrupted()
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        downloaded += n
                        if (downloaded - lastReport >= REPORT_EVERY) {
                            lastReport = downloaded
                            progress.onBytes(downloaded, total)
                        }
                    }
                }
            }
            progress.onBytes(downloaded, total ?: downloaded)
        } finally {
            connection.disconnect()
        }
    }

    private fun checkInterrupted() {
        if (Thread.currentThread().isInterrupted) throw InterruptedException()
    }

    private fun host(instance: String) = instance.substringAfter("://").substringBefore('/')

    private companion object {
        const val TAG = "SwiftDropCobalt"
        const val CONNECT_TIMEOUT_MS = 15_000
        const val READ_TIMEOUT_MS = 60_000
        const val BUFFER = 128 * 1024
        const val REPORT_EVERY = 256 * 1024L
    }
}
