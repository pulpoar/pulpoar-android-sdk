import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.pulpoar.sdk.consumer"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.pulpoar.sdk.consumer"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true }
    buildTypes {
        release {
            // R8 on, as a partner's release build would be.
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
}

kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }

val sdkVersion =
    providers.gradleProperty("sdkVersion").orNull
        ?: error("Pass -PsdkVersion=<released version>, for example -PsdkVersion=0.1.0")
val expectedEngine =
    providers.gradleProperty("expectedEngine").orNull
        ?: error("Pass -PexpectedEngine=<engine version the release pins>")

dependencies {
    implementation("com.pulpoar:tryon-ui:$sdkVersion")
    implementation(platform("androidx.compose:compose-bom:2025.08.00"))
    implementation("androidx.activity:activity-compose:1.10.1")
}

// The engine must be the one the release pins, whatever else the dependency graph asks for.
tasks.register("verifyResolvedEngine") {
    doLast {
        val artifacts =
            configurations
                .getByName("releaseRuntimeClasspath")
                .resolvedConfiguration
                .resolvedArtifacts
        val engine =
            artifacts.single {
                it.moduleVersion.id.group == "com.pulpoar" && it.name == "pulpo-module"
            }
        check(engine.moduleVersion.id.version == expectedEngine) {
            "Unexpected engine: ${engine.moduleVersion.id}, expected $expectedEngine"
        }
        println("Resolved ${engine.moduleVersion.id}")
    }
}
