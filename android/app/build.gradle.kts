plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.clipboardai.app"
    compileSdk = 35
    compileSdkExtension = 15
    defaultConfig {
        applicationId = "org.clipboardai.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 14
        versionName = "0.3.9"
    }
    flavorDimensions += "device"
    productFlavors {
        create("android") { dimension = "device" }
        create("harmony") {
            dimension = "device"
            applicationIdSuffix = ".harmony"
            minSdk = 31
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs.getByName("debug") {
        storeFile = rootProject.file("../.tools/debug.keystore")
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.isIncludeAndroidResources = true
    }
    lint { abortOnError = true }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
    // ZXing CaptureManager calls ContextCompat/ActivityCompat at runtime.
    implementation("androidx.core:core:1.15.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
