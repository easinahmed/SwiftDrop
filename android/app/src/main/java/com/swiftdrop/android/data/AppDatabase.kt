package com.swiftdrop.android.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [DownloadEntity::class, DownloadGroupEntity::class], version = 2, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {

    abstract fun downloads(): DownloadDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        /** 1.0 → 1.1: Spotify songs, and albums/playlists as groups. Keeps the download history. */
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE `downloads` ADD COLUMN `kind` TEXT")
                db.execSQL("ALTER TABLE `downloads` ADD COLUMN `groupId` INTEGER")
                db.execSQL("ALTER TABLE `downloads` ADD COLUMN `folder` TEXT")
                db.execSQL("ALTER TABLE `downloads` ADD COLUMN `spotify` TEXT")
                db.execSQL(CREATE_GROUPS)
            }
        }

        private const val CREATE_GROUPS = "CREATE TABLE IF NOT EXISTS `download_groups` (" +
            "`id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, `sourceUrl` TEXT NOT NULL, `name` TEXT NOT NULL, " +
            "`kind` TEXT NOT NULL, `imageUrl` TEXT, `partial` INTEGER NOT NULL, `createdAt` INTEGER NOT NULL)"

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "swiftdrop.db",
                ).addMigrations(MIGRATION_1_2).build().also { instance = it }
            }
    }
}
