package com.swiftdrop.android.spotify

import kotlin.coroutines.cancellation.CancellationException

/**
 * Runs [block], and once more if it fails with an error [shouldRetry] accepts. YouTube now and
 * then refuses (HTTP 403) a stream address it has just handed out; a fresh look works.
 */
suspend fun <T> retryOnceWhen(shouldRetry: (Throwable) -> Boolean, block: suspend () -> T): T =
    try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        if (!shouldRetry(e)) throw e
        block()
    }
