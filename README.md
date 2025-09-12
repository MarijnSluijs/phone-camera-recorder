Phone Camera Recorder (S23 Ultra‑Wide)

This project provides:
- An Android app that records video on a Samsung S23 using the ultra‑wide lens, starting at an exact epoch‑microseconds timestamp for a fixed duration.
- A cross‑platform desktop CLI (Windows/Linux) that schedules and triggers the recording via ADB.

High‑level flow
- CLI parses `--start-epoch-us` and `--duration-s` (seconds).
- CLI syncs device/host offset, waits/schedules, then launches the Android app with intent extras.
- Android app selects the ultra‑wide lens (if exposed via Camera2/CameraX) or zooms out to trigger ultra‑wide, and records for the requested duration.

Quick start
1) Prereqs: Install Android Platform Tools (adb), enable Developer Options + USB debugging on the phone.
2) Build & install the Android app (Gradle or Android Studio).
3) Use the CLI to trigger recording:
   pcr --duration-s 10 --start-epoch-us 1757685000000000 --lens ultra-wide
   pcr --duration-s 10 --start-epoch-us 0 --lens ultra-wide --no-audio # start immediately

Notes
- Exact ultra‑wide access is device/OS dependent. On many Samsung devices, the ultra‑wide is selected by setting zoom ratio < 1.0 via Camera2/CameraX. Fallback is the widest available camera.
- Exact start time relies on host↔device clock offset and adb latency; the CLI compensates, but sub‑100 ms accuracy may vary.
