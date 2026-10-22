package com.swiftdrop.android.ui

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.swiftdrop.android.core.LinkExtractor
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.SaveFolders
import com.swiftdrop.android.data.AppDatabase
import com.swiftdrop.android.data.AppSettings
import com.swiftdrop.android.data.EngineChannel
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.download.DownloadQueue
import com.swiftdrop.android.download.Downloads
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineErrors
import com.swiftdrop.android.engine.EngineState
import com.swiftdrop.android.engine.EngineUpdateResult
import com.swiftdrop.android.engine.EngineUpdateWorker
import com.swiftdrop.android.spotify.SpotifyLinks
import com.swiftdrop.android.youtube.YouTubeAccount
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application
    private val store = Settings.get(application)

    private val dao = AppDatabase.get(application).downloads()

    /** Downloads, with Spotify albums and playlists as a header over their songs. */
    val items: StateFlow<List<HomeItem>> = combine(dao.observeAll(), dao.observeGroups(), HomeItem::build)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val settings: StateFlow<AppSettings> = store.state
    val engineState: StateFlow<EngineState> = Engine.state
    val engineUpdating: StateFlow<Boolean> = Engine.updating
    val youTubeSignedIn: StateFlow<Boolean?> = YouTubeAccount.signedIn

    private val _tempBytes = MutableStateFlow<Long?>(null)
    /** Size of SwiftDrop's temporary files, or null while it is being measured. */
    val tempBytes: StateFlow<Long?> = _tempBytes.asStateFlow()

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
                    store.current.wifiOnly -> "Queued — waits for Wi-Fi"
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
        _messages.emit("Removed from the list. The file stays where it was saved.")
    }

    fun cancelGroup(groupId: Long) = viewModelScope.launch { Downloads.cancelGroup(app, groupId) }
    fun removeGroup(groupId: Long) = viewModelScope.launch {
        Downloads.removeGroup(app, groupId)
        _messages.emit("Removed from the list. The songs stay where they were saved.")
    }

    // -- Settings -----------------------------------------------------------------------------------

    fun update(transform: (AppSettings) -> AppSettings) = store.set(transform)

    fun setQuality(quality: Quality) = update { it.copy(quality = quality) }

    fun setWifiOnly(enabled: Boolean) = viewModelScope.launch {
        store.update { it.copy(wifiOnly = enabled) }
        EngineUpdateWorker.schedule(app)
    }

    fun setMaxParallel(value: Int) = viewModelScope.launch {
        store.update { it.copy(maxParallel = AppSettings.coerceParallel(value)) }
        DownloadQueue.pump(app) // more slots: start waiting downloads now
    }

    /** A folder picked with ACTION_OPEN_DOCUMENT_TREE: keep access to it across restarts. */
    fun chooseFolder(uri: Uri) = viewModelScope.launch {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        try {
            app.contentResolver.takePersistableUriPermission(uri, flags)
        } catch (e: SecurityException) {
            Log.w(TAG, "No lasting access to the chosen folder", e)
            _messages.emit("SwiftDrop can't keep access to that folder. Choose another one.")
            return@launch
        }
        val previous = store.current.downloadTree
        val label = SaveFolders.treeLabel(runCatching { DocumentsContract.getTreeDocumentId(uri) }.getOrNull())
        store.update { it.copy(downloadTree = uri.toString(), downloadTreeLabel = label) }
        if (previous != null && previous != uri.toString()) releaseFolder(previous)
        _messages.emit("New downloads go to $label")
    }

    fun resetFolder() = viewModelScope.launch {
        val previous = store.current.downloadTree
        store.update { it.copy(downloadTree = null, downloadTreeLabel = null) }
        previous?.let(::releaseFolder)
        _messages.emit("New downloads go to Download/SwiftDrop")
    }

    private fun releaseFolder(uri: String) {
        val flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        runCatching { app.contentResolver.releasePersistableUriPermission(Uri.parse(uri), flags) }
    }

    // -- Engine -------------------------------------------------------------------------------------

    fun updateEngine() = viewModelScope.launch {
        val result = Engine.update(app, store.current.engineChannel)
        _messages.emit(describe(result))
    }

    fun setEngineChannel(channel: EngineChannel) = viewModelScope.launch {
        if (store.current.engineChannel == channel) return@launch
        store.update { it.copy(engineChannel = channel) }
        // Switching channel installs that channel's build now (newer for Nightly, back for Stable).
        _messages.emit(describe(Engine.update(app, channel)))
    }

    private fun describe(result: EngineUpdateResult): String = when (result) {
        is EngineUpdateResult.Updated -> "Engine updated to ${result.version ?: "the latest version"}"
        is EngineUpdateResult.AlreadyUpToDate -> "Engine is up to date (${result.version ?: "latest"})"
        EngineUpdateResult.Busy -> EngineErrors.BUSY
        is EngineUpdateResult.Failed -> "Update failed: ${result.message}"
    }

    // -- YouTube account ----------------------------------------------------------------------------

    fun signOutOfYouTube() {
        YouTubeAccount.signOut(app) { _messages.tryEmit("Signed out of YouTube") }
    }

    // -- Storage and history ------------------------------------------------------------------------

    fun clearHistory() = viewModelScope.launch {
        Downloads.clearHistory(app)
        _messages.emit("Download history cleared. Your files are still there.")
    }

    fun measureTempFiles() = viewModelScope.launch {
        _tempBytes.value = withContext(Dispatchers.IO) { tempFiles().sumOf(::sizeOf) }
    }

    fun clearTempFiles() = viewModelScope.launch {
        val freed = withContext(Dispatchers.IO) {
            tempFiles().sumOf { file -> sizeOf(file).also { file.deleteRecursively() } }
        }
        _tempBytes.value = withContext(Dispatchers.IO) { tempFiles().sumOf(::sizeOf) }
        _messages.emit("Freed ${android.text.format.Formatter.formatShortFileSize(app, freed)}")
    }

    /** Everything in the cache folder except the work folders of downloads still running. */
    private suspend fun tempFiles(): List<File> {
        val active = dao.activeIds().map { it.toString() }.toSet()
        val cache = app.cacheDir
        return cache.listFiles().orEmpty().flatMap { entry ->
            if (entry.name == "downloads" && entry.isDirectory) {
                entry.listFiles().orEmpty().filter { it.name !in active }
            } else {
                listOf(entry)
            }
        }
    }

    private fun sizeOf(file: File): Long =
        if (file.isDirectory) file.walkTopDown().filter { it.isFile }.sumOf { it.length() } else file.length()

    private companion object {
        const val TAG = "SwiftDropSettings"
    }
}
