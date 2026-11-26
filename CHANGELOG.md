# Changelog

All notable changes to the PulpoAR Android SDK are listed here. Versions follow semantic versioning; every release
section states the engine it pins (`com.pulpoar:pulpo-module` for Try-On, `com.pulpoar:pulpo-skinai` for SkinAI).
Try-On and SkinAI each have their own version line; sections are headed `## Try-On <version>` or `## SkinAI <version>`, and releases are
tagged `tryon-<version>` or `skinai-<version>`. Releases up to Try-On 0.2.0 and SkinAI 0.2.0-rc.1 were tagged with the
bare version (`0.2.0`, `0.2.0-rc.1`).

## Unreleased

## Try-On 0.2.0

Try-On: `tryon-kit` and `tryon-ui` 0.2.0. Pins engine `com.pulpoar:pulpo-module:0.0.3`, unchanged from `0.1.0`.
**Breaking** for apps that call the Kit's `track*` methods or pass `PulpoTryOnUIConfiguration`'s `customizeTheme`
positionally; apps that only use `tryon-ui` with named arguments need no changes.

- **Try-on events, as the web plugin sends them:** new `PulpoTryOnEvent` (one subclass per web event, with the same
  data and the web's event name in `key`, such as `onAddToCart`). `PulpoTryOnSession.tryOnEvents` (a `Flow`) delivers
  every event to the app, whatever the analytics consent: the Kit's own (`Ready`, `Error`, `UsePhoto`, `VariantSelect`,
  `AppliedVariantsChange`, `TryOn`) and those a UI tracks. Collect it before `loadCatalog()` or `start` to get `Ready`;
  a slow collector keeps its latest 256.
- **tryon-ui:** `PulpoTryOnUIConfiguration(onEvent = ...)` receives every event on the main thread, for the app's own
  analytics. The live camera has a mirror button, as on the web.
- **tryon-kit:** `PulpoCameraView.isMirrored` (default `true`: the front camera shows as a mirror). Display only; photos
  and snapshots are never flipped.
- **Out-of-stock shades, as on the web:** listed and still try-on-able, labelled with the theme's out-of-stock text, without
  Add to cart, and left out of Add to cart all.
- **Removed (breaking):** `PulpoUIEvent` and the `track*` methods. Migrate with `track(event)`:
  - `trackUIEvent(PulpoUIEvent.X)` → `track(PulpoTryOnEvent.X)` (the names are kept)
  - `trackAddToCart(variants)` → `track(PulpoTryOnEvent.AddToCart(variants))`; likewise `trackGoToProduct`,
    `trackExperienceSelect`, `trackLookSelect`, `trackBrandSelect`, `trackCategorySelect` and `trackProductSelect`
  - The events the Kit sends itself are ignored by `track`, with a warning, so they aren't counted twice.
- **PulpoTryOnUIConfiguration:** `onEvent` is the new seventh parameter. A call passing `customizeTheme` as the seventh
  positional argument must name it; the trailing-lambda form (`PulpoTryOnUIConfiguration { theme -> ... }`) is unchanged.
- **Analytics, matching the web's reports:** `onReady` carries `entryType: "embedded"`; hiding and showing the try-on no
  longer counts the restored shades and photo as new choices; a project preloaded while another runs keeps its own visit.

## SkinAI 0.2.0-rc.1

First preview of SkinAI on Android: `skinai-kit` (skin analysis without UI), published as a Maven artifact on the
PulpoAR CDN. Pins engine `com.pulpoar:pulpo-skinai:0.2.0`.

- **Kit:** `PulpoSkinAIKit.configure`, then `PulpoSkinAnalyzer` to `prepare()` the models, `checkFace` a live frame,
  `analyze` a photo into a `PulpoSkinAnalysis`, and draw a `liveVisual` for one issue. `PulpoSkinAIProject` carries the
  project's concerns, questions and theme (`PulpoSkinAITheme`); `PulpoSkinAIKit.track` sends `PulpoSkinAIEvent` analytics.
- **16 KB page size:** the engine's 64-bit native libraries (`arm64-v8a`, `x86_64`) are 16 KB aligned.
- **No UI yet:** a ready-made `skinai-ui` comes in a later release. Not yet run on a 16 KB device by PulpoAR.

## Try-On 0.1.0

First final release. Pins engine `com.pulpoar:pulpo-module:0.0.3`.

- **Before/after on the live camera:** the compare button in `tryon-ui` now also shows on the live camera. In
  `tryon-kit`, `PulpoCameraView` gains `beforeAfterPosition`: the frame as it went in left of that fraction of the view's
  width, the try-on right of it, and `null` (the default) shows only the try-on.
- **Layout:** the intensity slider is centered under the right-side buttons, and the Look and Products card titles stay
  above the navigation bar's buttons on devices with three-button navigation.
- **16 KB page size:** the engine's 64-bit native libraries are aligned, as in `0.1.0-rc.2`, and PulpoAR has now run the
  SDK on a 16 KB device.

## Try-On 0.1.0-rc.2

Pins engine `com.pulpoar:pulpo-module:0.0.3`.

- **16 KB page size:** the engine's 64-bit native libraries (`arm64-v8a`, `x86_64`) are now 16 KB aligned, which Google
  Play requires for new apps targeting Android 15 or newer. `armeabi-v7a` and `x86` stay 4 KB; that is not required.
  Checked on the files in every release; not yet run on a 16 KB device by PulpoAR.
- **Engine startup fixes:** no crash when the engine failed to initialise, or when product data or texture names contain
  non-ASCII characters; an interrupted model download no longer leaves a cache that fails on every launch; a corrupt
  cached texture is deleted and downloaded again instead of crashing.
- The engine no longer ships a separate `libjsoncpp.so`.
- `tryon-kit` and `tryon-ui` are unchanged from `0.1.0-rc.1` apart from the engine pin. Not yet verified with a minified build on a device.

## Try-On 0.1.0-rc.1

First preview of the Android SDK for integration work: `tryon-ui` (ready-made try-on screens) and `tryon-kit`
(try-on without UI), published as Maven artifacts on the PulpoAR CDN. Pins engine `com.pulpoar:pulpo-module:0.0.2`.

**Not for production.** This engine's native libraries are not yet aligned for 16 KB memory pages. The SDK runs on
today's devices and emulators, but Google Play rejects uploads of new apps (targeting Android 15+) that contain it.
A later release replaces the engine; build your integration against this version and move to that one before you ship.
