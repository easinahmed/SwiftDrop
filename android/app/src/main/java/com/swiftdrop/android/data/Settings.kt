package com.swiftdrop.android.data

import android.content.Context
import android.util.Log
import androidx.datastore.core.DataStore
import androidx.datastore.core.handlers.ReplaceFileCorruptionHandler
import androidx.datastore.migrations.SharedPreferencesMigration
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.preferencesDataStoreFile
import com.swiftdrop.android.SwiftDropApp
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * User settings in DataStore, exposed as one [StateFlow] so the share sheet, workers and
 * notifications can read them instantly. The first read (and the one-time hand-over from
 * SwiftDrop 1.1's SharedPreferences) happens when the app process starts.
 */
class Settings private constructor(context: Context, private val scope: CoroutineScope) {

    private val store: DataStore<Preferences> = PreferenceDataStoreFactory.create(
        corruptionHandler = ReplaceFileCorruptionHandler { emptyPreferences() },
        migrations = listOf(
            SharedPreferencesMigration<Preferences>(
                context = context,
                sharedPreferencesName = LegacySettings.PREFS_NAME,
                keysToMigrate = LegacySettings.KEYS,
                migrate = { old, prefs -> LegacySettings.migrate(old.getAll(), prefs.toMutablePreferences()) },
            )
        ),
        scope = scope,
        produceFile = { context.preferencesDataStoreFile(FILE_NAME) },
    )

    private val _state = MutableStateFlow(runBlocking { readOnce() })
    val state: StateFlow<AppSettings> = _state.asStateFlow()

    /** The settings right now. */
    val current: AppSettings get() = _state.value

    init {
        scope.launch {
            store.data
                .catch { e -> if (e is IOException) emit(emptyPreferences()) else throw e }
                .map(SettingsKeys::read)
                .collect { _state.value = it }
        }
    }

    private suspend fun readOnce(): AppSettings = try {
        SettingsKeys.read(store.data.first())
    } catch (e: IOException) {
        Log.w(TAG, "Settings unreadable; using defaults", e)
        AppSettings()
    }

    /** Applies [transform] atomically and returns the new settings. */
    suspend fun update(transform: (AppSettings) -> AppSettings): AppSettings {
        var next = current
        store.edit { prefs ->
            next = transform(SettingsKeys.read(prefs))
            SettingsKeys.write(prefs, next)
        }
        _state.value = next
        return next
    }

    /** Fire-and-forget [update] for UI callbacks. */
    fun set(transform: (AppSettings) -> AppSettings) {
        scope.launch { update(transform) }
    }

    companion object {
        private const val TAG = "SwiftDropSettings"
        private const val FILE_NAME = "settings"

        @Volatile
        private var instance: Settings? = null

        fun get(context: Context): Settings =
            instance ?: synchronized(this) {
                instance ?: Settings(context.applicationContext, SwiftDropApp.scope).also { instance = it }
            }
    }
}
