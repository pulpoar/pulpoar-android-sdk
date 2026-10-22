# Changelog

All notable changes to the PulpoAR Android SDK are listed here. Versions follow semantic versioning; every release
section states the engine (`com.pulpoar:pulpo-module`) it pins.

## Unreleased

## 0.1.0-rc.1

First preview of the Android SDK for integration work: `tryon-ui` (ready-made try-on screens) and `tryon-kit`
(try-on without UI), published as Maven artifacts on the PulpoAR CDN. Pins engine `com.pulpoar:pulpo-module:0.0.2`.

**Not for production.** This engine's native libraries are not yet aligned for 16 KB memory pages. The SDK runs on
today's devices and emulators, but Google Play rejects uploads of new apps (targeting Android 15+) that contain it.
A later release replaces the engine; build your integration against this version and move to that one before you ship.
