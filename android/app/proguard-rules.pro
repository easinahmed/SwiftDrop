# Minification is disabled for SwiftDrop (see app/build.gradle.kts).
# If it is ever enabled, these keeps are the minimum the download engine needs:
-keep class com.yausername.** { *; }
-keep class com.fasterxml.jackson.** { *; }
-dontwarn com.fasterxml.jackson.**
