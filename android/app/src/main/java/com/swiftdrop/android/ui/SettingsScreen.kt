package com.swiftdrop.android.ui

import android.content.Intent
import android.text.format.Formatter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.swiftdrop.android.BuildConfig
import com.swiftdrop.android.core.AudioFormat
import com.swiftdrop.android.core.Mp3Bitrates
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.core.VideoFormat
import com.swiftdrop.android.data.AppSettings
import com.swiftdrop.android.data.EngineChannel
import com.swiftdrop.android.data.ShareAction
import com.swiftdrop.android.data.ThemeMode
import com.swiftdrop.android.engine.EngineState
import com.swiftdrop.android.youtube.YouTubeAccount
import com.swiftdrop.android.youtube.YouTubeLoginActivity
import kotlin.math.roundToInt

private const val WEBSITE = "https://swiftdrop-mac.vercel.app"

private enum class SettingsDialog {
    QUALITY, VIDEO_FORMAT, AUDIO_FORMAT, MP3_BITRATE, SHARE_ACTION, THEME, ENGINE_CHANNEL,
    CLEAR_HISTORY, LICENCES,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(viewModel: MainViewModel, onBack: () -> Unit) {
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val engineState by viewModel.engineState.collectAsStateWithLifecycle()
    val updating by viewModel.engineUpdating.collectAsStateWithLifecycle()
    val signedIn by viewModel.youTubeSignedIn.collectAsStateWithLifecycle()
    val tempBytes by viewModel.tempBytes.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    var dialog by rememberSaveable { mutableStateOf<SettingsDialog?>(null) }

    val pickFolder = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) viewModel.chooseFolder(uri)
    }
    val signIn = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        YouTubeAccount.refresh(context)
    }

    LaunchedEffect(Unit) {
        viewModel.measureTempFiles()
        viewModel.messages.collect { snackbar.showSnackbar(it) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings", fontWeight = FontWeight.SemiBold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp,
                end = 16.dp,
                top = padding.calculateTopPadding() + 4.dp,
                bottom = padding.calculateBottomPadding() + 24.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item(key = "downloads") {
                SettingsSection("Downloads") {
                    DownloadFolder(
                        settings = settings,
                        onChoose = { pickFolder.launch(null) },
                        onReset = viewModel::resetFolder,
                    )
                    SettingsDivider()
                    SwitchRow(
                        title = "Separate folders for Videos, Music and Other",
                        summary = "Sorts each file into a folder by kind",
                        checked = settings.separateFolders,
                        onCheckedChange = { on -> viewModel.update { it.copy(separateFolders = on) } },
                    )
                    SwitchRow(
                        title = "Albums and playlists in their own folder",
                        summary = "Each album or playlist gets a folder named after it",
                        checked = settings.groupFolders,
                        onCheckedChange = { on -> viewModel.update { it.copy(groupFolders = on) } },
                    )
                }
            }
            item(key = "video") {
                SettingsSection("Video") {
                    SettingRow(
                        title = "Default quality",
                        summary = qualitySummary(settings),
                        onClick = { dialog = SettingsDialog.QUALITY },
                    )
                    SettingRow(
                        title = "Format",
                        summary = settings.videoFormat.label,
                        onClick = { dialog = SettingsDialog.VIDEO_FORMAT },
                    )
                    SwitchRow(
                        title = "Prefer H.264 for compatibility",
                        summary = if (settings.videoFormat == VideoFormat.WEBM) {
                            "Not used for WebM, which can't hold H.264"
                        } else {
                            "Plays on every phone, TV and editor. Off: the most efficient codec (VP9 or AV1)"
                        },
                        checked = settings.preferH264,
                        enabled = settings.videoFormat != VideoFormat.WEBM,
                        onCheckedChange = { on -> viewModel.update { it.copy(preferH264 = on) } },
                    )
                }
            }
            item(key = "audio") {
                SettingsSection("Audio") {
                    SettingRow(
                        title = "Format",
                        summary = "${settings.audioFormat.label} · for audio-only downloads and Spotify songs",
                        onClick = { dialog = SettingsDialog.AUDIO_FORMAT },
                    )
                    SettingRow(
                        title = "MP3 bitrate",
                        summary = if (settings.audioFormat == AudioFormat.MP3) {
                            "${settings.mp3Bitrate} kbps"
                        } else {
                            "${settings.mp3Bitrate} kbps · used when the format is MP3"
                        },
                        enabled = settings.audioFormat == AudioFormat.MP3,
                        onClick = { dialog = SettingsDialog.MP3_BITRATE },
                    )
                }
            }
            item(key = "sharing") {
                SettingsSection("Sharing") {
                    SettingRow(
                        title = "When I share a link",
                        summary = settings.shareAction.label,
                        onClick = { dialog = SettingsDialog.SHARE_ACTION },
                    )
                }
            }
            item(key = "network") {
                SettingsSection("Network") {
                    SwitchRow(
                        title = "Wi-Fi only",
                        summary = "Wait for an unmetered network before downloading",
                        checked = settings.wifiOnly,
                        onCheckedChange = { viewModel.setWifiOnly(it) },
                    )
                    SettingsDivider()
                    ParallelDownloads(settings.maxParallel, viewModel::setMaxParallel)
                }
            }
            item(key = "notifications") {
                SettingsSection("Notifications") {
                    SwitchRow(
                        title = "Show progress notifications",
                        summary = if (settings.progressNotifications) {
                            "Progress bar and speed while downloading"
                        } else {
                            "Only a silent, minimised notice while downloading (Android requires one). " +
                                "You're still told when a download finishes."
                        },
                        checked = settings.progressNotifications,
                        onCheckedChange = { on -> viewModel.update { it.copy(progressNotifications = on) } },
                    )
                }
            }
            item(key = "appearance") {
                SettingsSection("Appearance") {
                    SettingRow(
                        title = "Theme",
                        summary = settings.theme.label,
                        onClick = { dialog = SettingsDialog.THEME },
                    )
                }
            }
            item(key = "youtube") {
                SettingsSection("YouTube") {
                    YouTubeAccountRow(
                        signedIn = signedIn == true,
                        onSignIn = { signIn.launch(Intent(context, YouTubeLoginActivity::class.java)) },
                        onSignOut = viewModel::signOutOfYouTube,
                    )
                    SettingsDivider()
                    SettingRow(
                        title = "Engine channel",
                        summary = when (settings.engineChannel) {
                            EngineChannel.STABLE -> "Stable · tested releases"
                            EngineChannel.NIGHTLY -> "Nightly · the newest fixes, updated daily"
                        },
                        onClick = { dialog = SettingsDialog.ENGINE_CHANNEL },
                    )
                    SwitchRow(
                        title = "Auto-update engine",
                        summary = "Updates yt-dlp when it is more than 3 days old",
                        checked = settings.engineAutoUpdate,
                        onCheckedChange = { on -> viewModel.update { it.copy(engineAutoUpdate = on) } },
                    )
                    EngineRow(
                        engineState = engineState,
                        updating = updating,
                        lastUpdate = settings.lastEngineUpdate,
                        onUpdate = viewModel::updateEngine,
                    )
                }
            }
            item(key = "storage") {
                SettingsSection("Storage and history") {
                    SettingRow(
                        title = "Clear download history",
                        summary = "Empties the list. Your files are kept.",
                        onClick = { dialog = SettingsDialog.CLEAR_HISTORY },
                    )
                    SettingRow(
                        title = "Clear temporary files",
                        summary = tempBytes?.let { "${Formatter.formatShortFileSize(context, it)} of leftovers and caches" }
                            ?: "Measuring…",
                        enabled = (tempBytes ?: 0L) > 0L,
                        onClick = viewModel::clearTempFiles,
                    )
                }
            }
            item(key = "about") {
                SettingsSection("About") {
                    SettingRow(
                        title = "Version",
                        summary = "SwiftDrop for Android ${BuildConfig.VERSION_NAME}",
                    )
                    SettingRow(
                        title = "Website",
                        summary = WEBSITE.removePrefix("https://"),
                        onClick = { FileActions.openWebsite(context, WEBSITE) },
                    )
                    SettingRow(
                        title = "Open-source licences",
                        summary = "yt-dlp, FFmpeg, youtubedl-android and more",
                        onClick = { dialog = SettingsDialog.LICENCES },
                    )
                    Text(
                        "Download only what you have the right to keep.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    )
                }
            }
            if (BuildConfig.DEBUG) {
                item(key = "developer") {
                    SettingsSection("Developer (debug build only)") {
                        SwitchRow(
                            title = "Simulate a YouTube bot check",
                            summary = "yt-dlp's YouTube answers look like \"Sign in to confirm you're not a bot\", " +
                                "so the cobalt fallback runs",
                            checked = settings.simulateBotCheck,
                            onCheckedChange = { on -> viewModel.update { it.copy(simulateBotCheck = on) } },
                        )
                    }
                }
            }
            item(key = "credit") {
                Text(
                    "Developed by Easin Codes",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                )
            }
        }
    }

    when (dialog) {
        SettingsDialog.QUALITY -> ChoiceDialog(
            title = "Default quality",
            options = Quality.entries,
            selected = settings.quality,
            label = { if (it.isAudio) "Audio only (${settings.audioFormat.label})" else it.label },
            note = {
                when (it) {
                    Quality.BEST -> "Highest resolution available (may be 4K or more)"
                    Quality.P1080 -> "Recommended"
                    Quality.AUDIO -> "Just the sound, in the audio format below"
                    else -> null
                }
            },
            onSelect = viewModel::setQuality,
            onDismiss = { dialog = null },
        )
        SettingsDialog.VIDEO_FORMAT -> ChoiceDialog(
            title = "Video format",
            options = VideoFormat.entries,
            selected = settings.videoFormat,
            label = { it.label },
            note = {
                when (it) {
                    VideoFormat.MP4 -> "Plays everywhere"
                    VideoFormat.MKV -> "Holds any codec without converting"
                    VideoFormat.WEBM -> "VP9 + Opus; MKV when a site has no WebM streams"
                }
            },
            onSelect = { format -> viewModel.update { it.copy(videoFormat = format) } },
            onDismiss = { dialog = null },
        )
        SettingsDialog.AUDIO_FORMAT -> ChoiceDialog(
            title = "Audio format",
            options = AudioFormat.entries,
            selected = settings.audioFormat,
            label = { it.label },
            note = {
                when (it) {
                    AudioFormat.M4A -> "AAC, usually without converting · plays everywhere"
                    AudioFormat.MP3 -> "Converted with the built-in FFmpeg · works with old players"
                    AudioFormat.OPUS -> "Smallest files at the same quality"
                }
            },
            onSelect = { format -> viewModel.update { it.copy(audioFormat = format) } },
            onDismiss = { dialog = null },
        )
        SettingsDialog.MP3_BITRATE -> ChoiceDialog(
            title = "MP3 bitrate",
            options = Mp3Bitrates.OPTIONS,
            selected = settings.mp3Bitrate,
            label = { "$it kbps" },
            note = {
                when (it) {
                    128 -> "Smaller files"
                    192 -> "Recommended"
                    else -> "Highest MP3 quality"
                }
            },
            onSelect = { kbps -> viewModel.update { it.copy(mp3Bitrate = kbps) } },
            onDismiss = { dialog = null },
        )
        SettingsDialog.SHARE_ACTION -> ChoiceDialog(
            title = "When I share a link",
            options = ShareAction.entries,
            selected = settings.shareAction,
            label = { it.label },
            note = {
                when (it) {
                    ShareAction.DOWNLOAD_NOW -> "Starts at the default quality, no questions"
                    ShareAction.ASK -> "Pick a video quality or audio each time"
                }
            },
            onSelect = { action -> viewModel.update { it.copy(shareAction = action) } },
            onDismiss = { dialog = null },
        )
        SettingsDialog.THEME -> ChoiceDialog(
            title = "Theme",
            options = ThemeMode.entries,
            selected = settings.theme,
            label = { it.label },
            onSelect = { theme -> viewModel.update { it.copy(theme = theme) } },
            onDismiss = { dialog = null },
        )
        SettingsDialog.ENGINE_CHANNEL -> ChoiceDialog(
            title = "Engine channel",
            options = EngineChannel.entries,
            selected = settings.engineChannel,
            label = { it.label },
            note = {
                when (it) {
                    EngineChannel.STABLE -> "Tested yt-dlp releases (recommended)"
                    EngineChannel.NIGHTLY -> "Daily yt-dlp builds: YouTube fixes arrive sooner"
                }
            },
            onSelect = viewModel::setEngineChannel,
            onDismiss = { dialog = null },
        )
        SettingsDialog.CLEAR_HISTORY -> ConfirmDialog(
            title = "Clear download history?",
            text = "Finished, failed and cancelled downloads leave the list. The files themselves stay where they were saved.",
            confirm = "Clear",
            onConfirm = viewModel::clearHistory,
            onDismiss = { dialog = null },
        )
        SettingsDialog.LICENCES -> LicencesDialog(onDismiss = { dialog = null })
        null -> Unit
    }
}

private fun qualitySummary(settings: AppSettings): String =
    if (settings.quality.isAudio) "Audio only (${settings.audioFormat.label})" else settings.quality.label

@Composable
private fun DownloadFolder(settings: AppSettings, onChoose: () -> Unit, onReset: () -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Download folder", style = MaterialTheme.typography.bodyLarge)
        Text(
            settings.downloadTreeLabel ?: SavePaths.RELATIVE_PATH,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilledTonalButton(onClick = onChoose) { Text("Choose folder…") }
            if (settings.usesCustomFolder) {
                OutlinedButton(onClick = onReset) { Text("Reset to default") }
            }
        }
    }
}

@Composable
private fun ParallelDownloads(value: Int, onChange: (Int) -> Unit) {
    var position by remember(value) { mutableFloatStateOf(value.toFloat()) }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Max simultaneous downloads", style = MaterialTheme.typography.bodyLarge)
                Text(
                    "Others wait their turn",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                position.roundToInt().toString(),
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Slider(
            value = position,
            onValueChange = { position = it },
            onValueChangeFinished = { onChange(position.roundToInt()) },
            valueRange = AppSettings.MIN_PARALLEL.toFloat()..AppSettings.MAX_PARALLEL.toFloat(),
            steps = AppSettings.MAX_PARALLEL - AppSettings.MIN_PARALLEL - 1,
        )
    }
}

@Composable
private fun YouTubeAccountRow(signedIn: Boolean, onSignIn: () -> Unit, onSignOut: () -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("YouTube account", style = MaterialTheme.typography.bodyLarge)
        Text(
            if (signedIn) {
                "Signed in. YouTube downloads use your account, which helps when YouTube asks to confirm you're not a bot."
            } else {
                "Optional. Signing in helps when YouTube blocks downloads or a video is age-restricted."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "Your login stays on this phone and is only used for YouTube downloads.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (signedIn) {
            OutlinedButton(onClick = onSignOut) { Text("Sign out") }
        } else {
            FilledTonalButton(onClick = onSignIn) { Text("Sign in") }
        }
    }
}

@Composable
private fun EngineRow(engineState: EngineState, updating: Boolean, lastUpdate: Long, onUpdate: () -> Unit) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val versionText = when (engineState) {
            EngineState.Initializing -> "Starting…"
            is EngineState.Ready -> "yt-dlp ${engineState.version ?: "(version unknown)"}"
            is EngineState.Failed -> "Unavailable: ${engineState.message}"
        }
        Text("Download engine", style = MaterialTheme.typography.bodyLarge)
        Text(versionText, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
        if (lastUpdate > 0) {
            Text(
                "Last checked " + android.text.format.DateUtils.getRelativeTimeSpanString(
                    lastUpdate, System.currentTimeMillis(), android.text.format.DateUtils.MINUTE_IN_MILLIS,
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        FilledTonalButton(onClick = onUpdate, enabled = !updating && engineState is EngineState.Ready) {
            if (updating) {
                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
                Text("Updating…")
            } else {
                Text("Update now")
            }
        }
    }
}

private data class Licence(val name: String, val licence: String, val url: String)

private val LICENCES = listOf(
    Licence("yt-dlp", "The Unlicense", "https://github.com/yt-dlp/yt-dlp/blob/master/LICENSE"),
    Licence("FFmpeg", "LGPL 2.1+ / GPL 2+", "https://ffmpeg.org/legal.html"),
    Licence("youtubedl-android", "GPL-3.0", "https://github.com/JunkFood02/youtubedl-android/blob/master/LICENSE"),
    Licence("Python", "PSF License", "https://docs.python.org/3/license.html"),
    Licence("QuickJS", "MIT", "https://bellard.org/quickjs/"),
    Licence("AndroidX, Jetpack Compose", "Apache 2.0", "https://www.apache.org/licenses/LICENSE-2.0"),
)

@Composable
private fun LicencesDialog(onDismiss: () -> Unit) {
    val context = LocalContext.current
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Open-source licences") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "SwiftDrop downloads with these projects. Tap one to read its licence.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                LICENCES.forEach { item ->
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .clickable { FileActions.openWebsite(context, item.url) }
                            .padding(vertical = 8.dp),
                    ) {
                        Text(item.name, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary)
                        Text(item.licence, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
}
