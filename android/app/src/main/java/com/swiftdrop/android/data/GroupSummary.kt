package com.swiftdrop.android.data

/** Where an album or playlist stands: "12 of 50 done · 2 not found". */
data class GroupSummary(
    val total: Int,
    val done: Int,
    val notFound: Int,
    val failed: Int,
    val cancelled: Int,
    val active: Int,
) {
    val finished: Int get() = total - active
    val isActive: Boolean get() = active > 0

    /** 0..1 */
    val fraction: Float get() = if (total == 0) 0f else finished.toFloat() / total

    fun line(): String = buildList {
        add("$done of $total done")
        if (notFound > 0) add("$notFound not found")
        if (failed > 0) add("$failed failed")
        if (cancelled > 0) add("$cancelled cancelled")
    }.joinToString(" · ")

    companion object {
        fun of(songs: List<DownloadEntity>) = GroupSummary(
            total = songs.size,
            done = songs.count { it.status == DownloadStatus.COMPLETED },
            notFound = songs.count { it.status == DownloadStatus.NO_MATCH },
            failed = songs.count { it.status == DownloadStatus.FAILED },
            cancelled = songs.count { it.status == DownloadStatus.CANCELLED },
            active = songs.count { it.status.isActive },
        )
    }
}
