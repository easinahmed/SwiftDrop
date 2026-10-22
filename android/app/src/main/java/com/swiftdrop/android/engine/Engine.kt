package com.swiftdrop.android.engine

import android.content.Context
import android.util.Log
import com.swiftdrop.android.data.EngineChannel
import com.swiftdrop.android.data.Settings
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import com.yausername.youtubedl_android.YoutubeDLResponse
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

sealed interface EngineState {
    data object Initializing : EngineState
    data class Ready(val version: String?) : EngineState
    data class Failed(val message: String) : EngineState
}

sealed interface EngineUpdateResult {
    data class Updated(val version: String?) : EngineUpdateResult
    data class AlreadyUpToDate(val version: String?) : EngineUpdateResult
    /** Downloads were running; replacing yt-dlp under them would break them. */
    data object Busy : EngineUpdateResult
    data class Failed(val message: String) : EngineUpdateResult
}

/**
 * yt-dlp (+ Python + FFmpeg) from youtubedl-android, initialised once per process.
 *
 * Updating replaces yt-dlp's files (the library deletes the folder, then copies the new build), so
 * an update only starts when no yt-dlp process is running, and new runs wait until it is done.
 */
object Engine {

    private const val TAG = "SwiftDropEngine"

    /** Automatic updates run when the engine is older than this. */
    val MAX_AGE_MS: Long = TimeUnit.DAYS.toMillis(3)
    /** …and not again within this long after an attempt (GitHub rate-limits update checks). */
    private val RETRY_AFTER_MS: Long = TimeUnit.HOURS.toMillis(6)
    /** The first YouTube download of a session waits at most this long for a fresh engine. */
    private val PRE_DOWNLOAD_UPDATE_TIMEOUT_MS: Long = TimeUnit.SECONDS.toMillis(90)

    private val started = AtomicBoolean(false)
    private val checkedBeforeYouTube = AtomicBoolean(false)
    private val updateLock = Mutex()
    /** Held while yt-dlp's files are being replaced; every run passes through it first. */
    private val filesGate = Mutex()
    private val running = MutableStateFlow(0)

    private val _state = MutableStateFlow<EngineState>(EngineState.Initializing)
    val state: StateFlow<EngineState> = _state.asStateFlow()

    private val _updating = MutableStateFlow(false)
    val updating: StateFlow<Boolean> = _updating.asStateFlow()

    /** Unpacks Python/yt-dlp/FFmpeg on first run (a few seconds), off the main thread. */
    fun start(context: Context, scope: CoroutineScope) {
        if (!started.compareAndSet(false, true)) return
        val app = context.applicationContext
        scope.launch(Dispatchers.IO) {
            _state.value = try {
                YoutubeDL.getInstance().init(app)
                FFmpeg.getInstance().init(app)
                EngineState.Ready(YoutubeDL.getInstance().version(app))
            } catch (t: Throwable) {
                Log.e(TAG, "Download engine failed to initialise", t)
                EngineState.Failed(t.message?.lineSequence()?.firstOrNull()?.take(200) ?: t.javaClass.simpleName)
            }
            // The library only records a version after its first update; ask yt-dlp itself.
            val ready = _state.value
            if (ready is EngineState.Ready && ready.version == null) {
                probeVersion()?.let { probed -> _state.compareAndSet(ready, EngineState.Ready(probed)) }
            }
            // Keep the engine current: YouTube changes often and old builds get blocked.
            updateIfStale(app)
        }
    }

    suspend fun awaitReady(): EngineState = state.first { it !is EngineState.Initializing }

    /**
     * Runs yt-dlp. Waits while an update replaces its files; cancelling the coroutine interrupts
     * the wait and kills the process.
     */
    suspend fun execute(
        request: YoutubeDLRequest,
        processTag: String,
        callback: (Float, Long, String) -> Unit = { _, _, _ -> },
    ): YoutubeDLResponse {
        filesGate.withLock { running.update { it + 1 } }
        val processId = "$processTag-${UUID.randomUUID()}"
        try {
            return runInterruptible(Dispatchers.IO) {
                YoutubeDL.getInstance().execute(request, processId, callback)
            }
        } finally {
            YoutubeDL.getInstance().destroyProcessById(processId)
            running.update { it - 1 }
        }
    }

    /** Installed yt-dlp version, e.g. "2025.11.12". Runs Python when the library hasn't recorded it. */
    fun version(context: Context): String? =
        runCatching { YoutubeDL.getInstance().version(context.applicationContext) }.getOrNull()
            ?: probeVersion()

    private fun probeVersion(): String? = runCatching {
        YoutubeDL.getInstance()
            .execute(YoutubeDLRequest(emptyList<String>()).addOption("--version"))
            .out.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }
    }.onFailure { Log.w(TAG, "Could not read the yt-dlp version", it) }.getOrNull()

    /**
     * Updates yt-dlp from [channel]. Safe to call from several places at once. Returns [EngineUpdateResult.Busy]
     * without touching anything while yt-dlp is running.
     */
    suspend fun update(context: Context, channel: EngineChannel): EngineUpdateResult =
        updateLock.withLock { updateLocked(context.applicationContext, channel) }

    private suspend fun updateLocked(app: Context, channel: EngineChannel): EngineUpdateResult {
        val ready = awaitReady()
        if (ready is EngineState.Failed) {
            return EngineUpdateResult.Failed("The engine isn't available: ${ready.message}")
        }
        return filesGate.withLock {
            if (running.value > 0) return EngineUpdateResult.Busy
            _updating.value = true
            try {
                val result = withContext(Dispatchers.IO) {
                    val status = YoutubeDL.getInstance().updateYoutubeDL(app, channel.toLibrary())
                    val newVersion = version(app)
                    _state.value = EngineState.Ready(newVersion)
                    if (status == YoutubeDL.UpdateStatus.DONE) {
                        EngineUpdateResult.Updated(newVersion)
                    } else {
                        EngineUpdateResult.AlreadyUpToDate(newVersion)
                    }
                }
                Settings.get(app).update { it.copy(lastEngineUpdate = System.currentTimeMillis()) }
                Log.i(TAG, "Engine update (${channel.name}): $result")
                result
            } catch (e: CancellationException) {
                throw e
            } catch (t: Throwable) {
                Log.w(TAG, "yt-dlp update failed", t)
                EngineUpdateResult.Failed(EngineErrors.describeUpdateFailure(t))
            } finally {
                _updating.value = false
            }
        }
    }

    /**
     * The automatic update: when "Auto-update engine" is on and the engine hasn't been updated for
     * [MAX_AGE_MS], updates it, unless a recent attempt failed or something is downloading.
     */
    suspend fun updateIfStale(context: Context): EngineUpdateResult? = updateLock.withLock {
        // Checked under the lock: when start-up and a download both ask, only one asks GitHub.
        val app = context.applicationContext
        val settings = Settings.get(app)
        val now = System.currentTimeMillis()
        val current = settings.current
        if (!current.engineAutoUpdate) return null
        if (!EngineErrors.isStale(current.lastEngineUpdate, now, MAX_AGE_MS)) return null
        if (now - current.lastEngineAttempt in 0 until RETRY_AFTER_MS) return null
        if (running.value > 0) return EngineUpdateResult.Busy
        settings.update { it.copy(lastEngineAttempt = now) }
        updateLocked(app, current.engineChannel)
    }

    /**
     * Before the first YouTube download of a session: brings a stale engine up to date (waiting up
     * to 90 s), so an outdated yt-dlp isn't what YouTube rejects. Skipped while other downloads run.
     */
    suspend fun freshenBeforeYouTube(context: Context) {
        if (checkedBeforeYouTube.get()) return
        val result = withTimeoutOrNull(PRE_DOWNLOAD_UPDATE_TIMEOUT_MS) { updateIfStale(context) }
        // Busy (another download is running) leaves the check for the next YouTube download.
        if (result !is EngineUpdateResult.Busy) checkedBeforeYouTube.set(true)
    }

    private fun EngineChannel.toLibrary(): YoutubeDL.UpdateChannel = when (this) {
        EngineChannel.STABLE -> YoutubeDL.UpdateChannel.STABLE
        EngineChannel.NIGHTLY -> YoutubeDL.UpdateChannel.NIGHTLY
    }
}
