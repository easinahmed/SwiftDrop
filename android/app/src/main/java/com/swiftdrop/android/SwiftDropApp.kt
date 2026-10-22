package com.swiftdrop.android

import android.app.Application
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.download.DownloadQueue
import com.swiftdrop.android.download.Notifications
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineUpdateWorker
import com.swiftdrop.android.youtube.YouTubeAccount
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class SwiftDropApp : Application() {

    override fun onCreate() {
        super.onCreate()
        // Loads settings (and hands over 1.1's) before the share sheet or a worker needs them.
        Settings.get(this)
        Notifications.createChannels(this)
        Engine.start(this, scope) // also updates a stale engine in the background
        EngineUpdateWorker.schedule(this)
        YouTubeAccount.refresh(this)
        val app = this
        scope.launch { DownloadQueue.pump(app) }
    }

    companion object {
        /** Process-wide scope for work that must outlive an Activity (e.g. enqueueing from the share sheet). */
        val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }
}
