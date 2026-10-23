import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

// Release signing lives outside the repo. Default:
//   ~/.swiftdrop/android/keystore.properties
// Override with the SWIFTDROP_KEYSTORE_PROPERTIES environment variable.
// Keys: storeFile, storePassword, keyAlias, keyPassword.
val keystorePropertiesFile: File = System.getenv("SWIFTDROP_KEYSTORE_PROPERTIES")
    ?.takeIf { it.isNotBlank() }
    ?.let { File(it) }
    ?: File(System.getProperty("user.home"), ".swiftdrop/android/keystore.properties")

val keystoreProperties: Properties? = keystorePropertiesFile
    .takeIf { it.isFile }
    ?.let { file -> Properties().apply { file.inputStream().use { load(it) } } }

if (keystoreProperties == null) {
    logger.warn(
        "SwiftDrop: no signing properties at ${keystorePropertiesFile.path}; " +
            "the release APK will be UNSIGNED (app-release-unsigned.apk). " +
            "Set SWIFTDROP_KEYSTORE_PROPERTIES or create that file to sign it."
    )
}

android {
    namespace = "com.swiftdrop.android"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "com.swiftdrop.android"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "1.2.1"
    }

    splits {
        abi {
            // yt-dlp's bundled Python and FFmpeg are native and make up most of the app, so each
            // phone ABI gets its own APK: almost every current phone needs only the arm64 one.
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a")
            isUniversalApk = false
        }
    }

    signingConfigs {
        if (keystoreProperties != null) {
            create("release") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                // Some phone makers' installers (OPPO ColorOS, for one) reject APKs without the
                // legacy v1 signature as "package appears to be invalid", so sign with every scheme.
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        debug {
            // Installs next to the signed release build, so testing never replaces its history.
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            // youtubedl-android ships no consumer keep rules and maps yt-dlp JSON with Jackson
            // reflection, so R8 stays off rather than risk stripping what it needs at runtime.
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystoreProperties != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        jniLibs {
            // The engine executes libpython.so / libffmpeg.so from nativeLibraryDir, so native
            // libraries must be extracted at install time (extractNativeLibs=true).
            useLegacyPackaging = true
        }
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

ksp {
    arg("room.generateKotlin", "true")
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.documentfile)
    implementation(libs.youtubedl.library)
    implementation(libs.youtubedl.ffmpeg)

    testImplementation(libs.junit)
    testImplementation(libs.org.json)
}
