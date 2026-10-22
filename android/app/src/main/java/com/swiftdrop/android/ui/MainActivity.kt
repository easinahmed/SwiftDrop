package com.swiftdrop.android.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.data.ThemeMode
import com.swiftdrop.android.ui.theme.SwiftDropTheme

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    private val permissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) askForPermissionsOnce()

        setContent {
            val settings by viewModel.settings.collectAsStateWithLifecycle()
            val dark = when (settings.theme) {
                ThemeMode.SYSTEM -> isSystemInDarkTheme()
                ThemeMode.LIGHT -> false
                ThemeMode.DARK -> true
            }
            LaunchedEffect(dark) {
                // Status and navigation bar icons follow the app's theme, not only the system's.
                val style = SystemBarStyle.auto(Color.TRANSPARENT, Color.TRANSPARENT) { dark }
                enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
            }
            SwiftDropTheme(settings.theme) {
                var showSettings by rememberSaveable { mutableStateOf(false) }
                BackHandler(enabled = showSettings) { showSettings = false }
                if (showSettings) {
                    SettingsScreen(viewModel = viewModel, onBack = { showSettings = false })
                } else {
                    HomeScreen(viewModel = viewModel, onOpenSettings = { showSettings = true })
                }
            }
        }
    }

    private fun askForPermissionsOnce() {
        val settings = Settings.get(this)
        val wanted = buildList {
            if (Build.VERSION.SDK_INT >= 33 && !settings.current.notificationPermissionAsked &&
                !granted(Manifest.permission.POST_NOTIFICATIONS)
            ) {
                settings.set { it.copy(notificationPermissionAsked = true) }
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
            if (SavePaths.needsLegacyWritePermission(Build.VERSION.SDK_INT) &&
                !granted(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            ) {
                add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
            }
        }
        if (wanted.isNotEmpty()) permissionRequest.launch(wanted.toTypedArray())
    }

    private fun granted(permission: String) =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
}
