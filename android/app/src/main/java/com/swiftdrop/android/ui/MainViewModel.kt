package com.swiftdrop.android.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.swiftdrop.android.core.LinkExtractor
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.download.Downloads
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineState
import com.swiftdrop.android.engine.EngineUpdateResult
import com.swiftdrop.android.engine.EngineUpdateWorker
import com.swiftdrop.android.spotify.SpotifyLinks
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application
    private val settings = Settings.get(application)

    private val dao = AppDatabase.get(application).downloads()

    /** Downloads, with Spotify albums and playlists as a header over their songs. */
    val items: StateFlow<List<HomeItem>> = combine(dao.observeAll(), dao.observeGroups(), HomeItem::build)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val quality: StateFlow<Quality> = settings.quality
    val wifiOnly: StateFlow<Boolean> = settings.wifiOnly
    val engineState: StateFlow<EngineState> = Engine.state
    val engineUpdating: StateFlow<Boolean> = Engine.updating

    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    /** Returns true when a link was found and queued. */
    fun download(text: String): Boolean {
        val url = LinkExtractor.firstUrl(text)
        if (url == null) {
            _messages.tryEmit("No link to download")
            return false
        }
        SpotifyLinks.refusal(url)?.let { refusal ->
            _messages.tryEmit(refusal)
            return false
        }
        viewModelScope.launch {
            Downloads.enqueue(app, url)
            _messages.emit(
                when {
                    settings.wifiOnly.value -> "Queued — waits for Wi-Fi"
                    SpotifyLinks.isSpotify(url) -> "Getting Spotify songs…"
                    else -> "Download started"
                }
            )
        }
        return true
    }

    fun cancel(id: Long) = viewModelScope.launch { Downloads.cancel(app, id) }
    fun retry(id: Long) = viewModelScope.launch { Downloads.retry(app, id) }
    fun remove(id: Long) = viewModelScope.launch {
        Downloads.remove(app, id)
        _messages.emit("Removed from the list. The file stays in Downloads.")
    }

    fun cancelGroup(groupId: Long) = viewModelScope.launch { Downloads.cancelGroup(app, groupId) }
    fun removeGroup(groupId: Long) = viewModelScope.launch {
        Downloads.removeGroup(app, groupId)
        _messages.emit("Removed from the list. The songs stay in Downloads.")
    }

    fun setQuality(quality: Quality) = settings.setQuality(quality)

    fun setWifiOnly(enabled: Boolean) {
        settings.setWifiOnly(enabled)
        EngineUpdateWorker.schedule(app)
    }

    fun updateEngine() = viewModelScope.launch {
        val result = Engine.update(app)
        val message = when (result) {
            is EngineUpdateResult.Updated -> "Engine updated to ${result.version ?: "the latest version"}"
            is EngineUpdateResult.AlreadyUpToDate -> "Engine is up to date (${result.version ?: "latest"})"
            is EngineUpdateResult.Failed -> "Update failed: ${result.message}"
        }
        if (result !is EngineUpdateResult.Failed) settings.lastEngineCheck = System.currentTimeMillis()
        _messages.emit(message)
    }
}
