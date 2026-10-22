package com.swiftdrop.android.ui

import android.content.ClipboardManager
import android.content.Context
import android.text.format.Formatter
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.swiftdrop.android.R
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.AppSettings
import com.swiftdrop.android.data.DownloadEntity
import com.swiftdrop.android.data.DownloadStatus
import com.swiftdrop.android.download.DownloadWorker
import com.swiftdrop.android.download.Downloads
import com.swiftdrop.android.engine.EngineState
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(viewModel: MainViewModel, onOpenSettings: () -> Unit) {
    val items by viewModel.items.collectAsStateWithLifecycle()
    val collapsed = remember { mutableStateMapOf<Long, Boolean>() }
    val engineState by viewModel.engineState.collectAsStateWithLifecycle()
    val settings by viewModel.settings.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current

    LaunchedEffect(Unit) {
        viewModel.messages.collect { snackbar.showSnackbar(it) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("SwiftDrop", fontWeight = FontWeight.SemiBold) },
                actions = {
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Filled.Settings, contentDescription = "Settings")
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
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item(key = "link") {
                LinkCard(settings = settings, engineState = engineState, onDownload = viewModel::download)
            }
            item(key = "header") {
                Text(
                    "Downloads",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(top = 8.dp, start = 4.dp),
                )
            }
            if (items.isEmpty()) {
                item(key = "empty") { EmptyState() }
            }
            for (entry in items) {
                when (entry) {
                    is HomeItem.Single -> item(key = "d-${entry.download.id}") {
                        DownloadRow(
                            item = entry.download,
                            onCancel = { viewModel.cancel(entry.download.id) },
                            onRetry = { viewModel.retry(entry.download.id) },
                            onOpen = { FileActions.open(context, entry.download) },
                            onShare = { FileActions.share(context, entry.download) },
                            onRemove = { viewModel.remove(entry.download.id) },
                        )
                    }
                    is HomeItem.Group -> {
                        val groupId = entry.group.id
                        val expanded = collapsed[groupId] != true
                        item(key = "g-$groupId") {
                            GroupHeader(
                                item = entry,
                                expanded = expanded,
                                onToggle = { collapsed[groupId] = expanded },
                                onCancel = { viewModel.cancelGroup(groupId) },
                                onRemove = { viewModel.removeGroup(groupId) },
                            )
                        }
                        if (expanded) {
                            items(entry.songs, key = { "d-${it.id}" }) { song ->
                                DownloadRow(
                                    item = song,
                                    compact = true,
                                    onCancel = { viewModel.cancel(song.id) },
                                    onRetry = { viewModel.retry(song.id) },
                                    onOpen = { FileActions.open(context, song) },
                                    onShare = { FileActions.share(context, song) },
                                    onRemove = { viewModel.remove(song.id) },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LinkCard(settings: AppSettings, engineState: EngineState, onDownload: (String) -> Boolean) {
    val context = LocalContext.current
    val focus = LocalFocusManager.current
    var text by rememberSaveable { mutableStateOf("") }

    fun submit() {
        if (onDownload(text)) {
            text = ""
            focus.clearFocus()
        }
    }

    Card(
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Paste a link", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                placeholder = { Text("https://…") },
                leadingIcon = { Icon(painterResource(R.drawable.ic_link), contentDescription = null) },
                trailingIcon = {
                    if (text.isNotEmpty()) {
                        IconButton(onClick = { text = "" }) {
                            Icon(Icons.Filled.Clear, contentDescription = "Clear")
                        }
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                keyboardActions = KeyboardActions(onGo = { submit() }),
                shape = RoundedCornerShape(16.dp),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                FilledTonalButton(
                    onClick = { readClipboard(context)?.let { text = it } },
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(painterResource(R.drawable.ic_paste), contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Paste")
                }
                Button(
                    onClick = { submit() },
                    enabled = text.isNotBlank(),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(painterResource(R.drawable.ic_download), contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Download")
                }
            }
            val hint = when (engineState) {
                is EngineState.Failed -> "Download engine unavailable: ${engineState.message}"
                EngineState.Initializing -> "Preparing the download engine…"
                is EngineState.Ready -> {
                    val quality = if (settings.quality.isAudio) {
                        "Audio (${settings.audioFormat.label})"
                    } else {
                        "${settings.quality.label} ${settings.videoFormat.label}"
                    }
                    val folder = settings.downloadTreeLabel ?: SavePaths.RELATIVE_PATH
                    "$quality · saves to $folder · or Share → SwiftDrop from any app"
                }
            }
            Text(
                hint,
                style = MaterialTheme.typography.bodySmall,
                color = if (engineState is EngineState.Failed) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun readClipboard(context: Context): String? {
    val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return null
    val clip = clipboard.primaryClip ?: return null
    if (clip.itemCount == 0) return null
    return clip.getItemAt(0).coerceToText(context)?.toString()?.trim()?.takeIf { it.isNotEmpty() }
}

@Composable
private fun EmptyState() {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 48.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(
            painterResource(R.drawable.ic_download),
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(40.dp),
        )
        Text("No downloads yet", style = MaterialTheme.typography.titleSmall)
        Text(
            "In YouTube, Chrome or any app, tap Share and pick SwiftDrop. Or paste a link above.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

/** A Spotify album or playlist: cover, name, "12 of 50 done · 2 not found", and its actions. */
@Composable
private fun GroupHeader(
    item: HomeItem.Group,
    expanded: Boolean,
    onToggle: () -> Unit,
    onCancel: () -> Unit,
    onRemove: () -> Unit,
) {
    val group = item.group
    val summary = item.summary
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Thumbnail(url = group.imageUrl, placeholderIcon = R.drawable.ic_music, modifier = Modifier.size(56.dp))
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        group.name,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        "Spotify ${group.kind} · ${summary.total} ${if (summary.total == 1) "song" else "songs"}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        summary.line(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Action(
                    if (expanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                    if (expanded) "Hide songs" else "Show songs",
                    onToggle,
                )
                if (summary.isActive) {
                    Action(Icons.Filled.Close, "Cancel all", onCancel)
                } else {
                    Action(Icons.Filled.Delete, "Remove from list", onRemove)
                }
            }
            if (group.partial) {
                Text(
                    "Spotify only shares the first 100 songs of a playlist.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            if (summary.isActive) {
                Spacer(Modifier.height(10.dp))
                LinearProgressIndicator(progress = { summary.fraction }, modifier = Modifier.fillMaxWidth())
            }
        }
    }
}

@Composable
private fun DownloadRow(
    item: DownloadEntity,
    onCancel: () -> Unit,
    onRetry: () -> Unit,
    onOpen: () -> Unit,
    onShare: () -> Unit,
    onRemove: () -> Unit,
    compact: Boolean = false,
) {
    val context = LocalContext.current
    val isAudio = item.mimeType?.startsWith("audio/") == true || item.quality == Quality.AUDIO.name
    Card(
        shape = RoundedCornerShape(if (compact) 16.dp else 20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLowest),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        modifier = if (compact) Modifier.padding(start = 16.dp) else Modifier,
    ) {
        Column(Modifier.padding(if (compact) 10.dp else 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Thumbnail(
                    url = item.thumbnailUrl,
                    placeholderIcon = if (isAudio) R.drawable.ic_music else R.drawable.ic_movie,
                    modifier = if (compact) Modifier.size(40.dp) else Modifier.size(width = 96.dp, height = 56.dp),
                )
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        item.title ?: item.fileName ?: item.url,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        statusLine(context, item, showFolder = !compact),
                        style = MaterialTheme.typography.bodySmall,
                        color = if (item.status == DownloadStatus.FAILED || item.status == DownloadStatus.NO_MATCH) {
                            MaterialTheme.colorScheme.error
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                // A song in an album or playlist keeps its main actions on the same line.
                if (compact) {
                    when (item.status) {
                        DownloadStatus.QUEUED, DownloadStatus.RUNNING -> Action(Icons.Filled.Close, "Cancel", onCancel)
                        DownloadStatus.COMPLETED -> {
                            Action(Icons.Filled.PlayArrow, "Open", onOpen)
                            Action(Icons.Filled.Share, "Share", onShare)
                        }
                        DownloadStatus.FAILED, DownloadStatus.CANCELLED, DownloadStatus.NO_MATCH ->
                            Action(Icons.Filled.Refresh, "Retry", onRetry)
                    }
                }
            }
            // A song waiting for its turn in an album or playlist shows no bar until it starts.
            if (item.status.isActive && !(compact && item.status == DownloadStatus.QUEUED)) {
                Spacer(Modifier.height(10.dp))
                if (item.status == DownloadStatus.RUNNING && item.progress > 0f) {
                    LinearProgressIndicator(
                        progress = { (item.progress / 100f).coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
            }
            if (!compact) Row(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp),
                horizontalArrangement = Arrangement.End,
            ) {
                when (item.status) {
                    DownloadStatus.QUEUED, DownloadStatus.RUNNING ->
                        Action(Icons.Filled.Close, "Cancel", onCancel)
                    DownloadStatus.COMPLETED -> {
                        Action(Icons.Filled.PlayArrow, "Open", onOpen)
                        Action(Icons.Filled.Share, "Share", onShare)
                        Action(Icons.Filled.Delete, "Remove from list", onRemove)
                    }
                    DownloadStatus.FAILED, DownloadStatus.CANCELLED, DownloadStatus.NO_MATCH -> {
                        Action(Icons.Filled.Refresh, "Retry", onRetry)
                        Action(Icons.Filled.Delete, "Remove from list", onRemove)
                    }
                }
            }
        }
    }
}

@Composable
private fun Action(icon: ImageVector, label: String, onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(icon, contentDescription = label, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private fun statusLine(context: Context, item: DownloadEntity, showFolder: Boolean): String {
    val site = item.site
    val detail = when (item.status) {
        DownloadStatus.QUEUED -> when {
            item.isSpotifyLink -> "Getting songs…"
            item.isSpotifySong -> "Waiting…"
            else -> "Waiting to start…"
        }
        DownloadStatus.RUNNING -> when {
            item.isSpotifyLink -> "Getting songs…"
            // Not matched yet: the site still says just "Spotify".
            item.isSpotifySong && item.progress <= 0f && item.site == Downloads.SPOTIFY -> "Finding the song on YouTube…"
            item.progress <= 0f -> "Starting…"
            else -> listOfNotNull("${item.progress.roundToInt()}%", item.speed).joinToString(" · ")
        }
        DownloadStatus.COMPLETED -> buildString {
            append("Saved")
            if (item.sizeBytes > 0) append(" · ").append(Formatter.formatShortFileSize(context, item.sizeBytes))
            if (showFolder) append(" · ").append(item.savedTo ?: SavePaths.relativePath(item.folder))
        }
        DownloadStatus.FAILED -> item.error ?: "Failed"
        DownloadStatus.CANCELLED -> "Cancelled"
        DownloadStatus.NO_MATCH -> DownloadWorker.NO_MATCH
    }
    return if (site.isNullOrBlank()) detail else "$site · $detail"
}
