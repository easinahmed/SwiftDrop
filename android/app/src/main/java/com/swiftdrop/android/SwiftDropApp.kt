package com.swiftdrop.android

import android.app.Application
import com.swiftdrop.android.download.Notifications
import com.swiftdrop.android.engine.Engine
import com.swiftdrop.android.engine.EngineUpdateWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class SwiftDropApp : Application() {

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
        Engine.start(this, scope)
        EngineUpdateWorker.schedule(this)
    }

    companion object {
        /** Process-wide scope for work that must outlive an Activity (e.g. enqueueing from the share sheet). */
        val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }
}
