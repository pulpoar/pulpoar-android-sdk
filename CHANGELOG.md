# Changelog

All notable changes to the PulpoAR Android SDK are listed here. Versions follow semantic versioning; every release
section states the engine (`com.pulpoar:pulpo-module`) it pins.

## Unreleased

## 0.1.0-rc.2

Pins engine `com.pulpoar:pulpo-module:0.0.3`.

- **16 KB page size:** the engine's 64-bit native libraries (`arm64-v8a`, `x86_64`) are now 16 KB aligned, which Google
  Play requires for new apps targeting Android 15 or newer. `armeabi-v7a` and `x86` stay 4 KB; that is not required.
  Checked on the files in every release; not yet run on a 16 KB device by PulpoAR.
- **Engine startup fixes:** no crash when the engine failed to initialise, or when product data or texture names contain
  non-ASCII characters; an interrupted model download no longer leaves a cache that fails on every launch; a corrupt
  cached texture is deleted and downloaded again instead of crashing.
- The engine no longer ships a separate `libjsoncpp.so`.
- `tryon-kit` and `tryon-ui` are unchanged from `0.1.0-rc.1` apart from the engine pin. Not yet verified with a minified build on a device.

## 0.1.0-rc.1

First preview of the Android SDK for integration work: `tryon-ui` (ready-made try-on screens) and `tryon-kit`
(try-on without UI), published as Maven artifacts on the PulpoAR CDN. Pins engine `com.pulpoar:pulpo-module:0.0.2`.

**Not for production.** This engine's native libraries are not yet aligned for 16 KB memory pages. The SDK runs on
today's devices and emulators, but Google Play rejects uploads of new apps (targeting Android 15+) that contain it.
A later release replaces the engine; build your integration against this version and move to that one before you ship.
