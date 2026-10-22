# PulpoAR Android SDK

Virtual try-on for native Android apps, as a Jetpack Compose view or as a headless Kit you build your own UI on.

This repository is the public home of the SDK: install instructions, changelog and release verification.
The libraries themselves are served as a Maven repository from the PulpoAR CDN. The source is private.

## Modules

| Maven artifact | Use it when |
| --- | --- |
| `com.pulpoar:tryon-ui` | You want the ready-made try-on: start screen, camera consent, live camera, photo capture, products and looks, styled with your Studio theme. One composable, `PulpoTryOnView`. Includes `tryon-kit`. |
| `com.pulpoar:tryon-kit` | You build your own UI. Session, camera view, catalog and product application, no screens. |

`tryon-ui` and `tryon-kit` always share one version. Each release comes with the exact rendering engine version it was tested with (pinned strictly in both the Gradle
metadata and the POM), so you cannot end up with an untested combination.

## Requirements

- Android 7.0 (API 24) or newer
- Built and tested with `compileSdk` 36, Android Gradle Plugin 8.13.2, Kotlin 2.2.21 and Java 17. Other versions may
  work but are not tested by the release checks. `tryon-ui` needs the Kotlin Compose compiler plugin (`org.jetbrains.kotlin.plugin.compose`).
- Native libraries ship for `arm64-v8a`, `armeabi-v7a`, `x86` and `x86_64`. The release checks run the build against the
  Gradle toolchain above; they do not run on a device or emulator.
- **16 KB page size: not supported yet.** The engine pinned by `0.1.0-rc.1` (`0.0.2`) is not 16 KB aligned, so an app
  built on it cannot be uploaded to Google Play as a new app targeting Android 15 or newer. It is fine for integration work
  on today's devices and emulators. A final version (without `-rc`) is only released with an aligned engine; the
  [changelog](CHANGELOG.md) and each version's `build-info.json` say which state a release is in.

The manifest permissions `INTERNET`, `ACCESS_NETWORK_STATE` and `CAMERA` are merged in by the SDK. The camera permission
is requested by the UI; photo uploads use the system photo picker and need no permission.

## Install

In `settings.gradle.kts`:

```kotlin
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://assets.pulpoar.com/vision/pulpo-sdk/android/maven")
            content { includeGroup("com.pulpoar") }
        }
    }
}
```

In your app module (pick the newest version from the [releases](../../releases)):

```kotlin
dependencies {
    implementation("com.pulpoar:tryon-ui:<version>")
}
```

Versions are immutable and the repository has no "latest" index: always pin an exact version.

## Use

### Ready-made UI (`tryon-ui`)

Configure the SDK once in your `Application`, then show the view in any composable. The UI asks for the camera
permission itself.

```kotlin
PulpoTryOn.configure(this, PulpoTryOnConfiguration(analyticsConsent = PulpoAnalyticsConsent.PENDING)) // Application.onCreate

PulpoTryOnView(projectSlug = "my-project", modifier = Modifier.fillMaxSize()) // in a composable
```

A complete walkthrough (consent, Add to Cart, theme, starting on a product or a look, Views-based apps) with a working app
is in the [Kotlin Try-On UI example](https://github.com/pulpoar/pulpoar-plugin-examples/tree/main/kotlin-tryon-ui-example).

### Your own UI (`tryon-kit`)

`PulpoTryOnSession` owns the camera, the catalog and the engine; `PulpoCameraView` shows the result. Request the camera
permission yourself before starting in camera mode. All calls are suspending and expect the main thread.

```kotlin
class TryOnActivity : ComponentActivity() {
    private val session = PulpoTryOnSession("my-project")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val view = PulpoCameraView(this).apply { bind(session) }
        setContentView(view)

        val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) startTryOn() else showMessage("Camera permission is needed")
        }
        permission.launch(Manifest.permission.CAMERA)
    }

    private fun startTryOn() = lifecycleScope.launch {
        try {
            session.start(PulpoTryOnSession.Mode.Camera(), lifecycleOwner = this@TryOnActivity)
            val catalog = session.catalog.value ?: return@launch
            val result = session.apply(listOf(catalog.variants.first()))
            result.rejected.forEach { log("not applied: ${it.variant.id} ${it.reason}") }
        } catch (error: PulpoException) {
            when (error) {
                is PulpoException.CameraPermissionDenied -> showMessage("Camera permission is needed")
                is PulpoException.Network -> showMessage("No connection")
                is PulpoException.UnsupportedDevice -> showMessage("Try-on is not available on this device")
                else -> showMessage("Try-on failed: ${error.message}")
            }
        }
    }

    override fun onDestroy() {
        lifecycleScope.launch(NonCancellable) { session.dispose() } // permanent; a stopped session can start again
        super.onDestroy()
    }
}
```

`session.state` reports `Idle`, `Loading`, `Running`, `Suspended`, `Failed` and `Disposed`; `session.stop()` releases the
camera and engine and keeps the session. `Mode.Photo` renders a bitmap you pass to `setPhoto` and needs no camera
permission. `setIntensity`, `clear`, `snapshot` and the `track*` analytics calls are on the same class. API reference
pages for the public classes are not published yet; the source of truth is the released AAR's Kotlin signatures (your IDE
shows the KDoc).

[`consumer/`](consumer) is a minimal app using the UI; the release workflow builds it against the published files.
Build it yourself:

```sh
cd consumer
./gradlew :app:assembleRelease -PsdkVersion=<version> -PexpectedEngine=<engine version from the changelog>
```

## Verification

Every file has `.sha256` and `.sha512` sidecars, and each version has a manifest,
`https://assets.pulpoar.com/vision/pulpo-sdk/android/tryon/<version>/build-info.json`, listing every file with its
size and SHA-256. Before a version is announced, the release workflow in this repository checks that what the CDN serves:

- matches the sizes and SHA-256 sums the build recorded, and that the manifest is saved in this repository as
  [`releases/<version>.json`](releases); a weekly job checks again that the CDN still serves exactly that,
- pins the right engine in the POMs, and
- for a final version, builds into a debug and a minified release app whose native libraries are all 16 KB aligned. A
  pre-release (`-rc.N`) may carry an engine that is not, and says so in its `build-info.json` and the changelog.

Run the same check yourself, with Python 3:

```sh
python3 scripts/verify_release.py <version> --expect releases/<version>.json
```

`--expect` compares the CDN's manifest with the one recorded in this repository when the version was released. Without it,
the script uses `releases/<version>.json` automatically if it sits next to the script (a clone of this repository).

Gradle can also pin the checksums of the files you use in your own build: generate
`gradle/verification-metadata.xml` with `./gradlew --write-verification-metadata sha256` and commit it.

Check an APK of your own with `python3 scripts/check_apk_16kb.py app-release.apk`.

## Updating

Change the version, sync, and read the [changelog](CHANGELOG.md). Engine updates arrive inside a Kit/UI release; the
changelog says which engine a release pins.

## Support and security

Questions: your PulpoAR contact. Vulnerabilities: see [SECURITY.md](SECURITY.md) and report them privately.

## License

Proprietary. Use requires an agreement with PulpoAR; see [LICENSE](LICENSE).
