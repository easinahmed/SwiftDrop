package com.swiftdrop.android.data

import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import com.swiftdrop.android.core.AudioFormat
import com.swiftdrop.android.core.FormatOptions
import com.swiftdrop.android.core.Mp3Bitrates
import com.swiftdrop.android.core.Quality
import com.swiftdrop.android.core.VideoFormat

enum class ShareAction(val label: String) {
    DOWNLOAD_NOW("Download right away"),
    ASK("Ask quality first"),
}

enum class ThemeMode(val label: String) {
    SYSTEM("System default"),
    LIGHT("Light"),
    DARK("Dark"),
}

enum class EngineChannel(val label: String) {
    STABLE("Stable"),
    NIGHTLY("Nightly"),
}

/** Every user setting, with its default. Stored in DataStore by [SettingsKeys]. */
data class AppSettings(
    // Downloads
    /** A folder picked with the system picker (persisted tree URI); null = Download/SwiftDrop. */
    val downloadTree: String? = null,
    /** "Movies/Clips" or "Clips (SD card)": how [downloadTree] is shown. */
    val downloadTreeLabel: String? = null,
    val separateFolders: Boolean = false,
    val groupFolders: Boolean = true,
    // Video and audio
    val quality: Quality = Quality.DEFAULT,
    val videoFormat: VideoFormat = VideoFormat.DEFAULT,
    val preferH264: Boolean = true,
    val audioFormat: AudioFormat = AudioFormat.DEFAULT,
    val mp3Bitrate: Int = Mp3Bitrates.DEFAULT,
    // Sharing, network, notifications, appearance
    val shareAction: ShareAction = ShareAction.DOWNLOAD_NOW,
    val wifiOnly: Boolean = false,
    val maxParallel: Int = DEFAULT_PARALLEL,
    val progressNotifications: Boolean = true,
    val theme: ThemeMode = ThemeMode.SYSTEM,
    // Download engine
    val engineChannel: EngineChannel = EngineChannel.STABLE,
    val engineAutoUpdate: Boolean = true,
    /** Last time the engine was updated or confirmed up to date. */
    val lastEngineUpdate: Long = 0L,
    /** Last automatic update attempt, successful or not (backs off after GitHub refuses). */
    val lastEngineAttempt: Long = 0L,
    // Internal
    val notificationPermissionAsked: Boolean = false,
    /** Debug builds only: make yt-dlp's YouTube result look like a bot check. */
    val simulateBotCheck: Boolean = false,
) {
    val formatOptions: FormatOptions
        get() = FormatOptions(videoFormat, preferH264, audioFormat, mp3Bitrate)

    val usesCustomFolder: Boolean get() = downloadTree != null

    companion object {
        const val MIN_PARALLEL = 1
        const val MAX_PARALLEL = 5
        const val DEFAULT_PARALLEL = 3

        fun coerceParallel(value: Int?): Int = (value ?: DEFAULT_PARALLEL).coerceIn(MIN_PARALLEL, MAX_PARALLEL)
    }
}

/** DataStore keys. The four 1.1 keys keep their SharedPreferences names. */
object SettingsKeys {
    // From SwiftDrop 1.1 (SharedPreferences "settings").
    val QUALITY = stringPreferencesKey("quality")
    val WIFI_ONLY = booleanPreferencesKey("wifi_only")
    val NOTIFICATION_ASKED = booleanPreferencesKey("notification_permission_asked")
    val LAST_ENGINE_UPDATE = longPreferencesKey("last_engine_check")

    // New in 1.2.
    val DOWNLOAD_TREE = stringPreferencesKey("download_tree")
    val DOWNLOAD_TREE_LABEL = stringPreferencesKey("download_tree_label")
    val SEPARATE_FOLDERS = booleanPreferencesKey("separate_folders")
    val GROUP_FOLDERS = booleanPreferencesKey("group_folders")
    val VIDEO_FORMAT = stringPreferencesKey("video_format")
    val PREFER_H264 = booleanPreferencesKey("prefer_h264")
    val AUDIO_FORMAT = stringPreferencesKey("audio_format")
    val MP3_BITRATE = intPreferencesKey("mp3_bitrate")
    val SHARE_ACTION = stringPreferencesKey("share_action")
    val MAX_PARALLEL = intPreferencesKey("max_parallel")
    val PROGRESS_NOTIFICATIONS = booleanPreferencesKey("progress_notifications")
    val THEME = stringPreferencesKey("theme")
    val ENGINE_CHANNEL = stringPreferencesKey("engine_channel")
    val ENGINE_AUTO_UPDATE = booleanPreferencesKey("engine_auto_update")
    val LAST_ENGINE_ATTEMPT = longPreferencesKey("last_engine_attempt")
    val SIMULATE_BOT_CHECK = booleanPreferencesKey("debug_simulate_bot_check")

    fun read(prefs: Preferences): AppSettings {
        val defaults = AppSettings()
        return AppSettings(
            downloadTree = prefs[DOWNLOAD_TREE]?.takeIf { it.isNotBlank() },
            downloadTreeLabel = prefs[DOWNLOAD_TREE_LABEL]?.takeIf { it.isNotBlank() },
            separateFolders = prefs[SEPARATE_FOLDERS] ?: defaults.separateFolders,
            groupFolders = prefs[GROUP_FOLDERS] ?: defaults.groupFolders,
            quality = Quality.fromKey(prefs[QUALITY]),
            videoFormat = VideoFormat.fromKey(prefs[VIDEO_FORMAT]),
            preferH264 = prefs[PREFER_H264] ?: defaults.preferH264,
            audioFormat = AudioFormat.fromKey(prefs[AUDIO_FORMAT]),
            mp3Bitrate = Mp3Bitrates.coerce(prefs[MP3_BITRATE]),
            shareAction = enumOr(prefs[SHARE_ACTION], defaults.shareAction),
            wifiOnly = prefs[WIFI_ONLY] ?: defaults.wifiOnly,
            maxParallel = AppSettings.coerceParallel(prefs[MAX_PARALLEL]),
            progressNotifications = prefs[PROGRESS_NOTIFICATIONS] ?: defaults.progressNotifications,
            theme = enumOr(prefs[THEME], defaults.theme),
            engineChannel = enumOr(prefs[ENGINE_CHANNEL], defaults.engineChannel),
            engineAutoUpdate = prefs[ENGINE_AUTO_UPDATE] ?: defaults.engineAutoUpdate,
            lastEngineUpdate = prefs[LAST_ENGINE_UPDATE] ?: defaults.lastEngineUpdate,
            lastEngineAttempt = prefs[LAST_ENGINE_ATTEMPT] ?: defaults.lastEngineAttempt,
            notificationPermissionAsked = prefs[NOTIFICATION_ASKED] ?: defaults.notificationPermissionAsked,
            simulateBotCheck = prefs[SIMULATE_BOT_CHECK] ?: defaults.simulateBotCheck,
        )
    }

    fun write(prefs: MutablePreferences, settings: AppSettings) {
        prefs.putOrRemove(DOWNLOAD_TREE, settings.downloadTree)
        prefs.putOrRemove(DOWNLOAD_TREE_LABEL, settings.downloadTreeLabel)
        prefs[SEPARATE_FOLDERS] = settings.separateFolders
        prefs[GROUP_FOLDERS] = settings.groupFolders
        prefs[QUALITY] = settings.quality.name
        prefs[VIDEO_FORMAT] = settings.videoFormat.name
        prefs[PREFER_H264] = settings.preferH264
        prefs[AUDIO_FORMAT] = settings.audioFormat.name
        prefs[MP3_BITRATE] = Mp3Bitrates.coerce(settings.mp3Bitrate)
        prefs[SHARE_ACTION] = settings.shareAction.name
        prefs[WIFI_ONLY] = settings.wifiOnly
        prefs[MAX_PARALLEL] = AppSettings.coerceParallel(settings.maxParallel)
        prefs[PROGRESS_NOTIFICATIONS] = settings.progressNotifications
        prefs[THEME] = settings.theme.name
        prefs[ENGINE_CHANNEL] = settings.engineChannel.name
        prefs[ENGINE_AUTO_UPDATE] = settings.engineAutoUpdate
        prefs[LAST_ENGINE_UPDATE] = settings.lastEngineUpdate
        prefs[LAST_ENGINE_ATTEMPT] = settings.lastEngineAttempt
        prefs[NOTIFICATION_ASKED] = settings.notificationPermissionAsked
        prefs[SIMULATE_BOT_CHECK] = settings.simulateBotCheck
    }

    private fun <T : Any> MutablePreferences.putOrRemove(key: Preferences.Key<T>, value: T?) {
        if (value == null) remove(key) else set(key, value)
    }

    private inline fun <reified E : Enum<E>> enumOr(name: String?, fallback: E): E =
        enumValues<E>().firstOrNull { it.name == name } ?: fallback
}

/**
 * SwiftDrop 1.1 kept four values in SharedPreferences ("settings"). DataStore's
 * SharedPreferencesMigration hands them over once, through [migrate], and then deletes the old file.
 */
object LegacySettings {

    const val PREFS_NAME = "settings"

    private const val QUALITY = "quality"
    private const val WIFI_ONLY = "wifi_only"
    private const val NOTIFICATION_ASKED = "notification_permission_asked"
    private const val LAST_ENGINE_CHECK = "last_engine_check"

    val KEYS = setOf(QUALITY, WIFI_ONLY, NOTIFICATION_ASKED, LAST_ENGINE_CHECK)

    /** Copies the 1.1 values (validated) into [prefs]; unknown or mistyped values are skipped. */
    fun migrate(old: Map<String, Any?>, prefs: MutablePreferences): MutablePreferences {
        (old[QUALITY] as? String)?.let { prefs[SettingsKeys.QUALITY] = Quality.fromKey(it).name }
        (old[WIFI_ONLY] as? Boolean)?.let { prefs[SettingsKeys.WIFI_ONLY] = it }
        (old[NOTIFICATION_ASKED] as? Boolean)?.let { prefs[SettingsKeys.NOTIFICATION_ASKED] = it }
        (old[LAST_ENGINE_CHECK] as? Long)?.let { prefs[SettingsKeys.LAST_ENGINE_UPDATE] = it }
        return prefs
    }
}
