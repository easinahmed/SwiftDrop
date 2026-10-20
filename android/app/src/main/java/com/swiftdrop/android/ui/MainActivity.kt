package com.swiftdrop.android.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import com.swiftdrop.android.core.SavePaths
import com.swiftdrop.android.data.Settings
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
            SwiftDropTheme {
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
        val wanted = buildList {
            val settings = Settings.get(this@MainActivity)
            if (Build.VERSION.SDK_INT >= 33 && !settings.notificationPermissionAsked &&
                !granted(Manifest.permission.POST_NOTIFICATIONS)
            ) {
                settings.notificationPermissionAsked = true
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
