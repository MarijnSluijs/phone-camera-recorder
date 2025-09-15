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
   pcr --duration-s 10 --start-epoch-us 0 --lens ultra-wide --no-audio # starts immediately

Notes
- Exact ultra‑wide access is device/OS dependent. On many Samsung devices, the ultra‑wide is selected by setting zoom ratio < 1.0 via Camera2/CameraX. Fallback is the widest available camera.
- Exact start time relies on host↔device clock offset and adb latency; the CLI compensates, but sub‑100 ms accuracy may vary.

## Desktop CLI (pcr)

Install (in a virtualenv)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ./desktop-cli
```

Usage
- Ensure adb is installed and the phone is connected with USB debugging enabled.
- Install the Android app APK on the phone.

Examples
- Start at a given epoch microseconds and record 5 seconds on ultra‑wide:
   pcr --start-epoch-us 1757685000000000 --duration-s 5 --lens ultra-wide

- Start now + 2s (Linux/macOS bash):
   now_us=$(($(date +%s%3N)*1000)); start_us=$((now_us + 2*1000000)); \
   pcr --start-epoch-us "$start_us" --duration-s 3

Notes
- The CLI syncs device/host time offset before scheduling.
- Start time is in DEVICE epoch microseconds.
