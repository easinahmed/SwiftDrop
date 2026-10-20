package com.swiftdrop.android.download

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.swiftdrop.android.core.EngineOutput
import com.swiftdrop.android.core.FileNames
import com.swiftdrop.android.core.FormatPlan
import com.swiftdrop.android.core.FormatSelector
import com.swiftdrop.android.core.LinkExtractor
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineState
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.YoutubeDLResponse
import java.io.File
import java.util.UUID
import kotlin.coroutines.cancellation.CancellationException
import kotlin.math.abs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.withContext

/**
 * One download: yt-dlp metadata (-J) → download into app storage → copy to Download/SwiftDrop.
 * Runs as a dataSync foreground service so it survives the app leaving the screen.
 */
class DownloadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    private val downloadId = inputData.getLong(KEY_DOWNLOAD_ID, -1L)
    private val dao by lazy { AppDatabase.get(applicationContext).downloads() }

    @Volatile private var title: String = "Download"

    override suspend fun getForegroundInfo(): ForegroundInfo =
        Notifications.foregroundInfo(applicationContext, downloadId, id, title, null, null)

    override suspend fun doWork(): Result {
        val item = dao.get(downloadId) ?: return Result.failure()
        val ctx = applicationContext
        title = item.title ?: LinkExtractor.hostOf(item.url).ifEmpty { item.url }

        showProgress(null, null) // become a foreground service first, while the share is still on screen
        dao.setStatus(downloadId, DownloadStatus.RUNNING)
        dao.setMetadata(downloadId, null, LinkExtractor.hostOf(item.url).ifEmpty { null }, null)
        Notifications.clearResult(ctx, downloadId)

        val workDir = File(ctx.cacheDir, "downloads/$downloadId")
        workDir.deleteRecursively()
        workDir.mkdirs()
        try {
            val engine = Engine.awaitReady()
            if (engine is EngineState.Failed) return fail("The download engine couldn't start: ${engine.message}")

            val plan = FormatSelector.plan(Quality.fromKey(item.quality))
            val info = fetchInfo(item.url, plan, workDir)
            title = info.title ?: title
            dao.setMetadata(downloadId, info.title, info.site, info.thumbnail)
            showProgress(0f, null)

            download(item.url, info, plan, workDir)

            val outputs = mediaOutputs(workDir)
            if (outputs.isEmpty()) return fail("The download finished but no file was produced.")
            var first: MediaSaver.Saved? = null
            for (file in outputs) {
                val name = if (outputs.size == 1) {
                    FileNames.displayName(info.title ?: file.nameWithoutExtension, file.extension)
                } else {
                    FileNames.displayName(file.nameWithoutExtension, file.extension)
                }
                val saved = MediaSaver.save(ctx, file, name, SavePaths.mimeType(name))
                file.delete()
                if (first == null) first = saved
            }
            val saved = checkNotNull(first)
            dao.setCompleted(downloadId, saved.uri.toString(), saved.displayName, saved.mimeType, saved.sizeBytes)
            Notifications.showCompleted(ctx, downloadId, title, saved.uri, saved.mimeType, outputs.size)
            return Result.success()
        } catch (e: CancellationException) {
            withContext(NonCancellable) {
                dao.markCancelledIfActive(downloadId)
                Notifications.clearProgress(ctx, downloadId)
            }
            throw e
        } catch (e: Throwable) {
            if (isStopped || e is YoutubeDL.CanceledException) {
                withContext(NonCancellable) { dao.markCancelledIfActive(downloadId) }
                Notifications.clearProgress(ctx, downloadId)
                return Result.failure()
            }
            Log.w(TAG, "Download $downloadId failed", e)
            val message = when (e) {
                is YoutubeDLException -> EngineOutput.readableError(e.message)
                else -> e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
            }
            return fail(message)
        } finally {
            workDir.deleteRecursively()
        }
    }

    private suspend fun fail(message: String): Result {
        withContext(NonCancellable) { dao.setFailed(downloadId, message) }
        Notifications.showFailed(applicationContext, downloadId, title, message)
        return Result.failure()
    }

    /** `yt-dlp -J`: title, site and thumbnail for the list, plus an info file to download from. */
    private suspend fun fetchInfo(url: String, plan: FormatPlan, workDir: File): MediaInfo {
        val request = YoutubeDLRequest(url).apply {
            addOption("-J")
            addOption("--flat-playlist")
            addCommonOptions(plan)
        }
        val response = runEngine(request) { _, _, _ -> }
        val infoFile = File(workDir, "info.json")
        infoFile.writeText(response.out)
        return MediaInfo.parse(response.out, url, infoFile)
    }

    private suspend fun download(url: String, info: MediaInfo, plan: FormatPlan, workDir: File) {
        // Reuse the extracted info so the site is only queried once; playlists go by URL.
        val request = if (info.isPlaylist) {
            YoutubeDLRequest(url)
        } else {
            YoutubeDLRequest(emptyList<String>()).addOption("--load-info-json", info.infoFile.absolutePath)
        }
        request.apply {
            addCommonOptions(plan)
            addOption("--newline")
            addOption("--no-mtime")
            addOption("-o", File(workDir, "%(title).150B [%(id)s].%(ext)s").absolutePath)
        }

        val progress = ProgressTracker(info.streamCount)
        coroutineScope {
            val publisher = launch {
                var lastPercent = -1f
                var lastSpeed: String? = null
                while (isActive) {
                    delay(PROGRESS_INTERVAL_MS)
                    val percent = progress.percent
                    val speed = progress.speed
                    if (abs(percent - lastPercent) >= 0.5f || speed != lastSpeed) {
                        lastPercent = percent
                        lastSpeed = speed
                        dao.setProgress(downloadId, percent, speed)
                        showProgress(percent, speed)
                    }
                }
            }
            try {
                runEngine(request) { percent, _, line -> progress.onLine(percent, line) }
            } finally {
                publisher.cancel()
            }
        }
        dao.setProgress(downloadId, 100f, null)
    }

    private fun YoutubeDLRequest.addCommonOptions(plan: FormatPlan) {
        addOption("--no-playlist")
        addOption("--cache-dir", File(applicationContext.cacheDir, "yt-dlp").absolutePath)
        addCommands(plan.toArgs())
    }

    /** Runs yt-dlp; cancelling the coroutine interrupts the wait and kills the process. */
    private suspend fun runEngine(
        request: YoutubeDLRequest,
        callback: (Float, Long, String) -> Unit,
    ): YoutubeDLResponse {
        val processId = "swiftdrop-$downloadId-${UUID.randomUUID()}"
        try {
            return runInterruptible(Dispatchers.IO) {
                YoutubeDL.getInstance().execute(request, processId, callback)
            }
        } finally {
            YoutubeDL.getInstance().destroyProcessById(processId)
        }
    }

    private var foreground = false

    private suspend fun showProgress(percent: Float?, speed: String?) {
        val ctx = applicationContext
        if (!foreground) {
            try {
                setForeground(Notifications.foregroundInfo(ctx, downloadId, id, title, percent, speed))
                foreground = true
                return
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                // Android 12+ refuses foreground services started from the background (e.g. a
                // Wi-Fi-only download that starts later). Keep going as a normal job.
                Log.w(TAG, "Could not run download $downloadId in the foreground", e)
            }
        }
        Notifications.showProgress(ctx, downloadId, id, title, percent, speed)
    }

    /** Folds per-stream progress (video then audio) into one 0–100 value. */
    private class ProgressTracker(private val streams: Int) {
        @Volatile var percent = 0f
            private set
        @Volatile var speed: String? = null
            private set
        private var stream = 0
        private var lastRaw = 0f

        @Synchronized
        fun onLine(raw: Float, line: String) {
            EngineOutput.speed(line)?.let { speed = it }
            if (raw < 0f || raw > 100f) return
            if (raw + 30f < lastRaw && stream < streams - 1) stream++
            lastRaw = raw
            percent = ((stream * 100f + raw) / streams).coerceIn(0f, 100f)
        }
    }

    companion object {
        const val KEY_DOWNLOAD_ID = "download_id"
        private const val TAG = "SwiftDropDownload"
        private const val PROGRESS_INTERVAL_MS = 700L

        private val TEMP_SUFFIXES = listOf(".part", ".ytdl", ".json", ".temp", ".tmp")
        /** Pre-merge streams look like "Title [id].f137.mp4". */
        private val INTERMEDIATE = Regex("""]\.f[^.\s]+\.[A-Za-z0-9]+$""")

        /** Finished media files, largest first; skips partials, metadata and pre-merge streams. */
        fun mediaOutputs(dir: File): List<File> =
            dir.listFiles().orEmpty()
                .filter { file ->
                    file.isFile && file.length() > 0 &&
                        TEMP_SUFFIXES.none { file.name.endsWith(it, ignoreCase = true) } &&
                        !file.name.contains(".part-Frag") &&
                        !INTERMEDIATE.containsMatchIn(file.name)
                }
                .sortedByDescending { it.length() }
    }
}
