package com.swiftdrop.android.download

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkInfo
import androidx.work.WorkerParameters
import com.swiftdrop.android.BuildConfig
import com.swiftdrop.android.cobalt.CobaltClient
import com.swiftdrop.android.cobalt.CobaltNames
import com.swiftdrop.android.cobalt.CobaltRequest
import com.swiftdrop.android.core.BotCheck
import com.swiftdrop.android.core.EngineOutput
import com.swiftdrop.android.core.FileNames
import com.swiftdrop.android.core.FormatOptions
import com.swiftdrop.android.core.FormatPlan
import com.swiftdrop.android.core.FormatSelector
import com.swiftdrop.android.core.LinkExtractor
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.core.YouTubeIds
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineState
import com.swiftdrop.android.spotify.Candidate
import com.swiftdrop.android.spotify.SongMatcher
import com.swiftdrop.android.spotify.SongState
import com.swiftdrop.android.spotify.YtDlpResults
import com.swiftdrop.android.spotify.retryOnceWhen
import com.swiftdrop.android.youtube.YouTubeAccount
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLException
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.YoutubeDLResponse
import java.io.File
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
 * One download: yt-dlp metadata (-J) → download into app storage → copy to the download folder.
 * Runs as a dataSync foreground service so it survives the app leaving the screen.
 *
 * When YouTube refuses yt-dlp with a bot check (common on mobile networks), the same video is
 * fetched once more through cobalt (see [CobaltClient]).
 *
 * A Spotify song first finds its recording on YouTube Music (or YouTube), then downloads that
 * as audio under the Spotify song's name and tags.
 */
class DownloadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    private val downloadId = inputData.getLong(KEY_DOWNLOAD_ID, -1L)
    private val dao by lazy { AppDatabase.get(applicationContext).downloads() }

    @Volatile private var title: String = "Download"

    override suspend fun getForegroundInfo(): ForegroundInfo =
        Notifications.foregroundInfo(applicationContext, downloadId, id, title, null, null)

    /** What a download produced, ready to be saved. */
    private class Produced(
        val files: List<File>,
        val title: String?,
        /** An album or playlist name: the files then get their own folder. */
        val collection: String?,
        val viaCobalt: Boolean,
    )

    override suspend fun doWork(): Result {
        val item = dao.get(downloadId) ?: return Result.failure()
        if (item.isSpotifySong) return songWork(item)
        val ctx = applicationContext
        if (!item.status.isActive) {
            DownloadQueue.pump(ctx) // cancelled while it waited for its turn
            return Result.success()
        }
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

            val settings = Settings.get(ctx).current
            val quality = Quality.fromKey(item.quality)
            val options = settings.formatOptions
            val youtube = YouTubeIds.isYouTubeUrl(item.url)
            if (youtube) Engine.freshenBeforeYouTube(ctx)

            val produced = try {
                downloadWithYtDlp(item.url, quality, options, workDir, youtube)
            } catch (e: YoutubeDLException) {
                if (!youtube || !BotCheck.isBotCheck(e.message)) throw e
                Log.i(TAG, "YouTube refused yt-dlp for download $downloadId; trying cobalt")
                downloadWithCobalt(item.url, quality, options, workDir, knownTitle = null)
                    ?: return fail(cobaltFailure ?: EngineOutput.readableError(e.message))
            }

            if (produced.files.isEmpty()) return fail("The download finished but no file was produced.")
            var first: MediaSaver.Saved? = null
            for (file in produced.files) {
                val name = if (produced.files.size == 1) {
                    FileNames.displayName(produced.title ?: file.nameWithoutExtension, file.extension)
                } else {
                    FileNames.displayName(file.nameWithoutExtension, file.extension)
                }
                val mimeType = SavePaths.mimeType(name)
                val saved = MediaSaver.save(ctx, file, name, mimeType, produced.collection)
                file.delete()
                if (first == null) first = saved
            }
            val saved = checkNotNull(first)
            dao.setCompleted(downloadId, saved.uri.toString(), saved.displayName, saved.mimeType, saved.sizeBytes, saved.location)
            Notifications.showCompleted(
                ctx, downloadId, title, saved.uri, saved.mimeType, produced.files.size, saved.location,
                note = if (saved.fellBackToDefault) "the chosen folder isn't available" else null,
            )
            return Result.success()
        } catch (e: CancellationException) {
            withContext(NonCancellable) {
                // Stopped by the system (constraints, quota): WorkManager runs it again, so it keeps its slot.
                if (stopReason == WorkInfo.STOP_REASON_CANCELLED_BY_APP) dao.markCancelledIfActive(downloadId)
                Notifications.clearProgress(ctx, downloadId)
            }
            throw e
        } catch (e: Throwable) {
            if (e is YoutubeDL.CanceledException || e is InterruptedException) {
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
            withContext(NonCancellable) { DownloadQueue.pump(ctx) }
        }
    }

    private suspend fun downloadWithYtDlp(
        url: String,
        quality: Quality,
        options: FormatOptions,
        workDir: File,
        youtube: Boolean,
    ): Produced {
        val plan = FormatSelector.plan(quality, options)
        val auth = if (youtube) cookiesFor(workDir) else null
        simulateBotCheckIfAsked(url, youtube)
        val info = fetchInfo(url, plan, workDir, auth)
        title = info.title ?: title
        dao.setMetadata(downloadId, info.title, info.site, info.thumbnail)
        showProgress(0f, null)
        download(url, info, plan, workDir, auth)
        val collection = if (info.isPlaylist && Settings.get(applicationContext).current.groupFolders) info.title else null
        return Produced(mediaOutputs(workDir), info.title, collection, viaCobalt = false)
    }

    /** Why the last cobalt attempt failed, in plain words. */
    private var cobaltFailure: String? = null

    /**
     * The same video through cobalt: streams the file it hands back into [workDir], with progress.
     * Returns null (and sets [cobaltFailure]) when no server could fetch it.
     */
    private suspend fun downloadWithCobalt(
        url: String,
        quality: Quality,
        options: FormatOptions,
        workDir: File,
        knownTitle: String?,
    ): Produced? {
        workDir.listFiles()?.forEach { if (it.isFile) it.delete() } // yt-dlp's partial files
        val videoId = YouTubeIds.videoId(url)
        val site = (LinkExtractor.hostOf(url).ifEmpty { "youtube.com" }) + VIA_COBALT
        dao.setMetadata(downloadId, null, site, videoId?.let(YouTubeIds::thumbnail))
        showProgress(0f, null)
        dao.setProgress(downloadId, 0f, null)

        val request = CobaltRequest.build(url, quality, options)
        val client = CobaltClient(userAgent = "SwiftDrop-Android/${BuildConfig.VERSION_NAME}")
        val progress = TransferProgress()
        val outcome = coroutineScope {
            val publisher = launch {
                var lastPercent = -1f
                while (isActive) {
                    delay(PROGRESS_INTERVAL_MS)
                    val now = progress.percent
                    val speed = progress.speed()
                    if (abs(now - lastPercent) >= 0.5f) {
                        lastPercent = now
                        dao.setProgress(downloadId, now, speed)
                        showProgress(now, speed)
                    }
                }
            }
            try {
                runInterruptible(Dispatchers.IO) {
                    client.download(request, workDir) { downloaded, total -> progress.update(downloaded, total) }
                }
            } finally {
                publisher.cancel()
            }
        }
        return when (outcome) {
            is CobaltClient.Outcome.Saved -> {
                Log.i(TAG, "Download $downloadId fetched via cobalt (${outcome.instance})")
                val cobaltTitle = knownTitle ?: CobaltNames.title(outcome.filename)
                if (cobaltTitle != null) {
                    title = cobaltTitle
                    dao.setMetadata(downloadId, cobaltTitle, null, null)
                }
                dao.setProgress(downloadId, 100f, null)
                Produced(listOf(outcome.file), cobaltTitle, collection = null, viaCobalt = true)
            }
            is CobaltClient.Outcome.Failed -> {
                cobaltFailure = outcome.message
                null
            }
        }
    }

    /**
     * Debug builds only (Settings → Developer): YouTube answers as if this network were flagged, so
     * the cobalt fallback can be tested on a network YouTube doesn't block.
     */
    private fun simulateBotCheckIfAsked(url: String, youtube: Boolean) {
        if (!BuildConfig.DEBUG || !youtube || !Settings.get(applicationContext).current.simulateBotCheck) return
        val id = YouTubeIds.videoId(url) ?: "video"
        throw YoutubeDLException(
            "ERROR: [youtube] $id: Sign in to confirm you’re not a bot. Use --cookies-from-browser or " +
                "--cookies for the authentication. (simulated by SwiftDrop's debug setting)"
        )
    }

    /**
     * The YouTube sign-in, copied for this job: yt-dlp writes its cookie jar back when it exits,
     * and several downloads must not write the same file at once. Lives in a sub-folder so it is
     * never mistaken for a downloaded file, and goes with the work folder.
     */
    private fun cookiesFor(workDir: File): File? {
        val source = YouTubeAccount.cookieFileIfSignedIn(applicationContext) ?: return null
        val dir = File(workDir, ".auth").apply { mkdirs() }
        val copy = File(dir, "cookies.txt")
        source.copyTo(copy, overwrite = true)
        copy.setReadable(false, false)
        copy.setReadable(true, true)
        return copy
    }

    // -- Spotify songs ------------------------------------------------------------------------------

    private suspend fun songWork(item: DownloadEntity): Result {
        val ctx = applicationContext
        if (!item.status.isActive) {
            DownloadQueue.pump(ctx) // cancelled while it waited for its turn
            return Result.success()
        }
        val workDir = File(ctx.cacheDir, "downloads/$downloadId")
        try {
            val state = SongState.fromJson(item.spotify)
                ?: return songFailed(item, "This song's Spotify details are missing. Share the Spotify link again.")
            val track = state.track
            title = track.display
            showProgress(null, null)
            dao.setStatus(downloadId, DownloadStatus.RUNNING)
            Notifications.clearResult(ctx, downloadId)

            val engine = Engine.awaitReady()
            if (engine is EngineState.Failed) return songFailed(item, "The download engine couldn't start: ${engine.message}")
            Engine.freshenBeforeYouTube(ctx)

            // A retried or resumed song reuses its recording instead of searching again.
            val match: Candidate = state.match ?: run {
                val search = YtDlpSongSearch(File(ctx.cacheDir, "yt-dlp")) { request -> runEngine(request) { _, _, _ -> }.out }
                val found = SongMatcher(search).find(track)
                if (found == null) {
                    withContext(NonCancellable) { dao.setNoMatch(downloadId, NO_MATCH) }
                    if (item.groupId == null) Notifications.showFailed(ctx, downloadId, title, NO_MATCH)
                    return Result.success()
                }
                dao.setSpotify(downloadId, state.copy(match = found).toJson())
                found
            }
            val site = if (match.music) SITE_MUSIC else SITE_YOUTUBE
            dao.setMetadata(downloadId, null, site, null)
            Log.i(TAG, "Song $downloadId matched to YouTube ${match.videoId}")

            val url = "https://www.youtube.com/watch?v=${match.videoId}"
            val options = Settings.get(ctx).current.formatOptions
            val plan = FormatSelector.plan(Quality.AUDIO, options)
            val file = try {
                retryOnceWhen({ it is YoutubeDLException && EngineOutput.isForbidden(it.message) }) {
                    workDir.deleteRecursively()
                    workDir.mkdirs()
                    val auth = cookiesFor(workDir)
                    simulateBotCheckIfAsked(url, youtube = true)
                    val info = fetchInfo(url, plan, workDir, auth)
                    info.infoFile.writeText(YtDlpResults.withSongTags(info.infoFile.readText(), track, match.album))
                    showProgress(0f, null)
                    download(url, info, plan, workDir, auth, listOf("--embed-metadata"))
                }
                mediaOutputs(workDir).firstOrNull()
            } catch (e: YoutubeDLException) {
                if (!BotCheck.isBotCheck(e.message)) throw e
                Log.i(TAG, "YouTube refused yt-dlp for song $downloadId; trying cobalt")
                val produced = downloadWithCobalt(url, Quality.AUDIO, options, workDir, knownTitle = track.display)
                    ?: return songFailed(item, cobaltFailure ?: EngineOutput.readableError(e.message))
                dao.setMetadata(downloadId, track.display, site + VIA_COBALT, null)
                produced.files.firstOrNull()
            } ?: return songFailed(item, "The download finished but no file was produced.")

            val name = track.fileName(file.extension)
            val mimeType = SavePaths.mimeType(name)
            val collection = item.folder?.takeIf { Settings.get(ctx).current.groupFolders }
            val saved = MediaSaver.save(ctx, file, name, mimeType, collection)
            file.delete()
            dao.setCompleted(downloadId, saved.uri.toString(), saved.displayName, saved.mimeType, saved.sizeBytes, saved.location)
            if (item.groupId == null) {
                Notifications.showCompleted(ctx, downloadId, title, saved.uri, saved.mimeType, 1, saved.location)
            } else {
                Notifications.clearProgress(ctx, downloadId)
            }
            return Result.success()
        } catch (e: CancellationException) {
            withContext(NonCancellable) {
                // Stopped by the system (constraints, quota): WorkManager runs it again, so it keeps its slot.
                if (stopReason == WorkInfo.STOP_REASON_CANCELLED_BY_APP) dao.markCancelledIfActive(downloadId)
                Notifications.clearProgress(ctx, downloadId)
            }
            throw e
        } catch (e: Throwable) {
            if (e is YoutubeDL.CanceledException || e is InterruptedException) {
                withContext(NonCancellable) { dao.markCancelledIfActive(downloadId) }
                Notifications.clearProgress(ctx, downloadId)
                return Result.failure()
            }
            Log.w(TAG, "Song $downloadId failed", e)
            val message = when (e) {
                is YoutubeDLException -> EngineOutput.readableError(e.message)
                else -> e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName
            }
            return songFailed(item, message)
        } finally {
            workDir.deleteRecursively()
            withContext(NonCancellable) {
                item.groupId?.let { Notifications.updateGroup(ctx, it) }
                DownloadQueue.pump(ctx)
            }
        }
    }

    private suspend fun songFailed(item: DownloadEntity, message: String): Result {
        withContext(NonCancellable) { dao.setFailed(downloadId, message) }
        if (item.groupId == null) {
            Notifications.showFailed(applicationContext, downloadId, title, message)
        } else {
            Notifications.clearProgress(applicationContext, downloadId)
        }
        return Result.failure()
    }

    private suspend fun fail(message: String): Result {
        withContext(NonCancellable) { dao.setFailed(downloadId, message) }
        Notifications.showFailed(applicationContext, downloadId, title, message)
        return Result.failure()
    }

    /** `yt-dlp -J`: title, site and thumbnail for the list, plus an info file to download from. */
    private suspend fun fetchInfo(url: String, plan: FormatPlan, workDir: File, cookies: File?): MediaInfo {
        val request = YoutubeDLRequest(url).apply {
            addOption("-J")
            addOption("--flat-playlist")
            addCommonOptions(plan, cookies)
        }
        val response = runEngine(request) { _, _, _ -> }
        val infoFile = File(workDir, "info.json")
        infoFile.writeText(response.out)
        return MediaInfo.parse(response.out, url, infoFile)
    }

    private suspend fun download(
        url: String,
        info: MediaInfo,
        plan: FormatPlan,
        workDir: File,
        cookies: File?,
        extraOptions: List<String> = emptyList(),
    ) {
        // Reuse the extracted info so the site is only queried once; playlists go by URL.
        val request = if (info.isPlaylist) {
            YoutubeDLRequest(url)
        } else {
            YoutubeDLRequest(emptyList<String>()).addOption("--load-info-json", info.infoFile.absolutePath)
        }
        request.apply {
            addCommonOptions(plan, cookies)
            addOption("--newline")
            addOption("--no-mtime")
            addOption("-o", File(workDir, "%(title).150B [%(id)s].%(ext)s").absolutePath)
            addCommands(extraOptions)
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

    private fun YoutubeDLRequest.addCommonOptions(plan: FormatPlan, cookies: File?) {
        addOption("--no-playlist")
        addOption("--cache-dir", File(applicationContext.cacheDir, "yt-dlp").absolutePath)
        // The YouTube sign-in (Settings), only ever passed for YouTube links.
        if (cookies != null) addOption("--cookies", cookies.absolutePath)
        addCommands(plan.toArgs())
    }

    /** Runs yt-dlp; cancelling the coroutine interrupts the wait and kills the process. */
    private suspend fun runEngine(
        request: YoutubeDLRequest,
        callback: (Float, Long, String) -> Unit,
    ): YoutubeDLResponse = Engine.execute(request, "swiftdrop-$downloadId", callback)

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

    /** Progress of a plain HTTP transfer (the cobalt fallback). */
    private class TransferProgress {
        private val started = System.currentTimeMillis()
        @Volatile var percent = 0f
            private set
        @Volatile private var bytes = 0L

        fun update(downloaded: Long, total: Long?) {
            bytes = downloaded
            if (total != null && total > 0) percent = (downloaded * 100f / total).coerceIn(0f, 99.5f)
        }

        fun speed(): String? {
            val elapsedMs = (System.currentTimeMillis() - started).coerceAtLeast(1)
            return EngineOutput.formatSpeed(bytes * 1000 / elapsedMs)
        }
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
        const val NO_MATCH = "No match found"
        const val SITE_MUSIC = "Spotify · YouTube Music"
        const val SITE_YOUTUBE = "Spotify · YouTube"
        /** Appended to the row's site when the file came through the cobalt fallback. */
        const val VIA_COBALT = " · via cobalt"
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
