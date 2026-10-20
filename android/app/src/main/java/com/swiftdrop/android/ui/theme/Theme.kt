package com.swiftdrop.android.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Same accent as the SwiftDrop desktop app and website.
private val Light = lightColorScheme(
    primary = Color(0xFF2F6DF6),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDCE6FF),
    onPrimaryContainer = Color(0xFF0B2A6B),
    secondary = Color(0xFF6A5CF0),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE6E2FF),
    onSecondaryContainer = Color(0xFF221A6B),
    background = Color(0xFFF7F8FC),
    surface = Color(0xFFF7F8FC),
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF1F3FA),
    surfaceContainer = Color(0xFFEBEEF7),
    surfaceContainerHigh = Color(0xFFE5E8F2),
    error = Color(0xFFC62828),
)

private val Dark = darkColorScheme(
    primary = Color(0xFF7FB0FF),
    onPrimary = Color(0xFF00296B),
    primaryContainer = Color(0xFF1F4BB0),
    onPrimaryContainer = Color(0xFFDCE6FF),
    secondary = Color(0xFFB9B0FF),
    onSecondary = Color(0xFF2A1F87),
    secondaryContainer = Color(0xFF3F35A8),
    onSecondaryContainer = Color(0xFFE6E2FF),
    background = Color(0xFF0F1115),
    surface = Color(0xFF0F1115),
    surfaceContainerLowest = Color(0xFF0B0D10),
    surfaceContainerLow = Color(0xFF171A20),
    surfaceContainer = Color(0xFF1C2027),
    surfaceContainerHigh = Color(0xFF242934),
    error = Color(0xFFFF8A80),
)

@Composable
fun SwiftDropTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
