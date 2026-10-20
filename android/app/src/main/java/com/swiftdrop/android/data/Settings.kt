package com.swiftdrop.android.data

import android.content.Context
import android.content.SharedPreferences
import com.swiftdrop.android.core.Quality
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Small synchronous settings store; ShareActivity must read the quality instantly. */
class Settings private constructor(private val prefs: SharedPreferences) {

    private val _quality = MutableStateFlow(Quality.fromKey(prefs.getString(KEY_QUALITY, null)))
    val quality: StateFlow<Quality> = _quality.asStateFlow()

    private val _wifiOnly = MutableStateFlow(prefs.getBoolean(KEY_WIFI_ONLY, false))
    val wifiOnly: StateFlow<Boolean> = _wifiOnly.asStateFlow()

    fun setQuality(quality: Quality) {
        prefs.edit().putString(KEY_QUALITY, quality.name).apply()
        _quality.value = quality
    }

    fun setWifiOnly(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_WIFI_ONLY, enabled).apply()
        _wifiOnly.value = enabled
    }

    var notificationPermissionAsked: Boolean
        get() = prefs.getBoolean(KEY_NOTIFICATION_ASKED, false)
        set(value) = prefs.edit().putBoolean(KEY_NOTIFICATION_ASKED, value).apply()

    var lastEngineCheck: Long
        get() = prefs.getLong(KEY_LAST_ENGINE_CHECK, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_ENGINE_CHECK, value).apply()

    companion object {
        private const val KEY_QUALITY = "quality"
        private const val KEY_WIFI_ONLY = "wifi_only"
        private const val KEY_NOTIFICATION_ASKED = "notification_permission_asked"
        private const val KEY_LAST_ENGINE_CHECK = "last_engine_check"

        @Volatile
        private var instance: Settings? = null

        fun get(context: Context): Settings =
            instance ?: synchronized(this) {
                instance ?: Settings(
                    context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)
                ).also { instance = it }
            }
    }
}
