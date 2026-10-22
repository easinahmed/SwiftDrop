package com.swiftdrop.android.share

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import com.swiftdrop.android.R
import com.swiftdrop.android.core.Quality

/** "Ask quality first": video quality chips, Audio, and Cancel, over the app the link came from. */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun QualitySheet(
    host: String,
    defaultQuality: Quality,
    audioLabel: String,
    videoLabel: String,
    onPick: (Quality) -> Unit,
    onCancel: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onCancel, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Download with SwiftDrop", style = MaterialTheme.typography.titleLarge)
            if (host.isNotEmpty()) {
                Text(host, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text("Video ($videoLabel)", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Quality.VIDEO.forEach { quality ->
                    QualityChip(
                        label = quality.shortLabel,
                        highlighted = quality == defaultQuality,
                        icon = R.drawable.ic_movie,
                        onClick = { onPick(quality) },
                    )
                }
            }
            Text("Audio", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            QualityChip(
                label = "Audio only · $audioLabel",
                highlighted = defaultQuality.isAudio,
                icon = R.drawable.ic_music,
                onClick = { onPick(Quality.AUDIO) },
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onCancel) { Text("Cancel") }
            }
        }
    }
}

@Composable
private fun QualityChip(label: String, highlighted: Boolean, icon: Int, onClick: () -> Unit) {
    AssistChip(
        onClick = onClick,
        label = { Text(label) },
        leadingIcon = { Icon(painterResource(icon), contentDescription = null, modifier = Modifier.size(18.dp)) },
        colors = if (highlighted) {
            AssistChipDefaults.assistChipColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer,
                labelColor = MaterialTheme.colorScheme.onPrimaryContainer,
                leadingIconContentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        } else {
            AssistChipDefaults.assistChipColors()
        },
    )
}
