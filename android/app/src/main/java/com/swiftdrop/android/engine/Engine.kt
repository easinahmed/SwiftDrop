package com.swiftdrop.android.engine

import android.content.Context
import android.util.Log
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import java.io.FileNotFoundException
import java.io.IOException
import java.net.UnknownHostException
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

sealed interface EngineState {
    data object Initializing : EngineState
    data class Ready(val version: String?) : EngineState
    data class Failed(val message: String) : EngineState
}

sealed interface EngineUpdateResult {
    data class Updated(val version: String?) : EngineUpdateResult
    data class AlreadyUpToDate(val version: String?) : EngineUpdateResult
    data class Failed(val message: String) : EngineUpdateResult
}

/** yt-dlp (+ Python + FFmpeg) from youtubedl-android, initialised once per process. */
object Engine {

    private const val TAG = "SwiftDropEngine"

    private val started = AtomicBoolean(false)
    private val updateLock = Mutex()

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
        }
    }

    suspend fun awaitReady(): EngineState = state.first { it !is EngineState.Initializing }

    /** Installed yt-dlp version, e.g. "2025.11.12". Runs Python when the library hasn't recorded it. */
    fun version(context: Context): String? =
        runCatching { YoutubeDL.getInstance().version(context.applicationContext) }.getOrNull()
            ?: probeVersion()

    private fun probeVersion(): String? = runCatching {
        YoutubeDL.getInstance()
            .execute(YoutubeDLRequest(emptyList<String>()).addOption("--version"))
            .out.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }
    }.onFailure { Log.w(TAG, "Could not read the yt-dlp version", it) }.getOrNull()

    /** Updates yt-dlp from its stable channel. Safe to call from several places at once. */
    suspend fun update(context: Context): EngineUpdateResult = updateLock.withLock {
        val app = context.applicationContext
        val ready = awaitReady()
        if (ready is EngineState.Failed) {
            return EngineUpdateResult.Failed("The engine isn't available: ${ready.message}")
        }
        _updating.value = true
        try {
            withContext(Dispatchers.IO) {
                val status = YoutubeDL.getInstance().updateYoutubeDL(app, YoutubeDL.UpdateChannel.STABLE)
                val newVersion = version(app)
                _state.value = EngineState.Ready(newVersion)
                if (status == YoutubeDL.UpdateStatus.DONE) {
                    EngineUpdateResult.Updated(newVersion)
                } else {
                    EngineUpdateResult.AlreadyUpToDate(newVersion)
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "yt-dlp update failed", t)
            EngineUpdateResult.Failed(describeUpdateFailure(t))
        } finally {
            _updating.value = false
        }
    }

    /** The library wraps everything in "failed to update youtube-dl"; say what actually went wrong. */
    private fun describeUpdateFailure(t: Throwable): String {
        val causes = generateSequence(t) { it.cause }.toList()
        return when {
            causes.any { it is UnknownHostException } -> "No internet connection. Try again when you're online."
            // GitHub answers 403/404 when it rate-limits unauthenticated update checks.
            causes.any { it is FileNotFoundException } || causes.any { it.message?.contains("403") == true } ->
                "GitHub is limiting update checks from this network right now. Try again in an hour."
            causes.any { it is IOException } -> "Couldn't reach GitHub to download the update. Try again later."
            else -> t.message?.lineSequence()?.firstOrNull()?.take(200) ?: "Update failed"
        }
    }
}
