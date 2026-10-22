package com.swiftdrop.android.data

import androidx.datastore.core.DataMigration
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import com.swiftdrop.android.core.AudioFormat
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.VideoFormat
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsMigrationTest {

    private val dir: File = Files.createTempDirectory("swiftdrop-settings").toFile()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @After
    fun tearDown() {
        scope.cancel()
        dir.deleteRecursively()
    }

    /** What SwiftDrop 1.1 stored in SharedPreferences "settings". */
    private val legacy = mapOf<String, Any?>(
        "quality" to "AUDIO",
        "wifi_only" to true,
        "notification_permission_asked" to true,
        "last_engine_check" to 1_760_000_000_000L,
    )

    @Test
    fun migrate_keepsEvery1_1Value() {
        val prefs = LegacySettings.migrate(legacy, emptyPreferences().toMutablePreferences())
        val settings = SettingsKeys.read(prefs)
        assertEquals(Quality.AUDIO, settings.quality)
        assertTrue(settings.wifiOnly)
        assertTrue(settings.notificationPermissionAsked)
        assertEquals(1_760_000_000_000L, settings.lastEngineUpdate)
        // New settings start at their defaults.
        assertEquals(AppSettings().copy(
            quality = Quality.AUDIO,
            wifiOnly = true,
            notificationPermissionAsked = true,
            lastEngineUpdate = 1_760_000_000_000L,
        ), settings)
    }

    @Test
    fun migrate_skipsUnknownOrMistypedValues() {
        val prefs = LegacySettings.migrate(
            mapOf("quality" to "P4320", "wifi_only" to "yes", "last_engine_check" to 5, "other" to 1),
            emptyPreferences().toMutablePreferences(),
        )
        val settings = SettingsKeys.read(prefs)
        assertEquals(Quality.DEFAULT, settings.quality)
        assertFalse(settings.wifiOnly)
        assertEquals(0L, settings.lastEngineUpdate)
        assertEquals(AppSettings(), settings)
    }

    @Test
    fun everyOldQualityName_survives() {
        for (name in listOf("BEST", "P1080", "P720", "P480", "AUDIO")) {
            val prefs = LegacySettings.migrate(mapOf("quality" to name), emptyPreferences().toMutablePreferences())
            assertEquals(name, SettingsKeys.read(prefs).quality.name)
        }
    }

    @Test
    fun dataStore_runsTheMigrationOnce_thenKeepsNewValues() = runBlocking {
        var handedOver = false
        val oldPrefs = legacy.toMutableMap()
        // Stands in for DataStore's SharedPreferencesMigration, which calls the same mapper.
        val migration = object : DataMigration<Preferences> {
            override suspend fun shouldMigrate(currentData: Preferences) = oldPrefs.isNotEmpty()
            override suspend fun migrate(currentData: Preferences): Preferences =
                LegacySettings.migrate(oldPrefs, currentData.toMutablePreferences())
            override suspend fun cleanUp() {
                oldPrefs.clear()
                handedOver = true
            }
        }
        val store = PreferenceDataStoreFactory.create(
            migrations = listOf(migration),
            scope = scope,
            produceFile = { File(dir, "settings.preferences_pb") },
        )
        val first = SettingsKeys.read(store.data.first())
        assertTrue(handedOver)
        assertEquals(Quality.AUDIO, first.quality)
        assertTrue(first.wifiOnly)

        store.edit { prefs ->
            SettingsKeys.write(prefs, SettingsKeys.read(prefs).copy(videoFormat = VideoFormat.MKV, audioFormat = AudioFormat.MP3, mp3Bitrate = 320))
        }
        val after = SettingsKeys.read(store.data.first())
        assertEquals(VideoFormat.MKV, after.videoFormat)
        assertEquals(AudioFormat.MP3, after.audioFormat)
        assertEquals(320, after.mp3Bitrate)
        assertEquals(Quality.AUDIO, after.quality) // the migrated value is still there
    }

    @Test
    fun readWrite_roundTripsEverySetting() {
        val custom = AppSettings(
            downloadTree = "content://com.android.externalstorage.documents/tree/primary%3AMovies",
            downloadTreeLabel = "Movies",
            separateFolders = true,
            groupFolders = false,
            quality = Quality.P1440,
            videoFormat = VideoFormat.WEBM,
            preferH264 = false,
            audioFormat = AudioFormat.OPUS,
            mp3Bitrate = 128,
            shareAction = ShareAction.ASK,
            wifiOnly = true,
            maxParallel = 5,
            progressNotifications = false,
            theme = ThemeMode.DARK,
            engineChannel = EngineChannel.NIGHTLY,
            engineAutoUpdate = false,
            lastEngineUpdate = 42L,
            lastEngineAttempt = 43L,
            notificationPermissionAsked = true,
            simulateBotCheck = true,
        )
        val prefs = emptyPreferences().toMutablePreferences()
        SettingsKeys.write(prefs, custom)
        assertEquals(custom, SettingsKeys.read(prefs))
        // Clearing the folder removes it.
        SettingsKeys.write(prefs, custom.copy(downloadTree = null, downloadTreeLabel = null))
        assertEquals(null, SettingsKeys.read(prefs).downloadTree)
    }

    @Test
    fun outOfRangeValues_areCoerced() {
        val prefs = emptyPreferences().toMutablePreferences()
        prefs[SettingsKeys.MAX_PARALLEL] = 9
        prefs[SettingsKeys.MP3_BITRATE] = 96
        prefs[SettingsKeys.THEME] = "NEON"
        val settings = SettingsKeys.read(prefs)
        assertEquals(AppSettings.MAX_PARALLEL, settings.maxParallel)
        assertEquals(192, settings.mp3Bitrate)
        assertEquals(ThemeMode.SYSTEM, settings.theme)
    }
}
