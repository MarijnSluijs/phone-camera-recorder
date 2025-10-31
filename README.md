# Phone Camera Recorder (Android + Desktop CLI)

This project provides:
- An Android app that records video controlled via desktop, starting at an exact epoch‑microseconds timestamp for a fixed duration.
- A cross‑platform desktop CLI (Windows/Linux) that schedules and triggers the recording via ADB.
- Tested on Samsung S23.

## Android phone setup
1) Install Android Platform Tools (adb) on computer: https://developer.android.com/tools/releases/platform-tools
2) Enable Developer Options + USB debugging on the phone.
3) Connect phone to computer. Build & install the Android app  via Gradle or Android Studio.

## Desktop CLI setup
Install (in a virtualenv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./desktop-cli
```

#### Usage
- Ensure adb is installed and the phone is connected via USB, with USB debugging enabled.
- Install the Android app APK on the phone:
```bash
cd android-app
.\gradlew.bat installDebug
adb install -r .android\app\build\outputs\apk\debug\app-debug.apk
```
- Run the desktop CLI `pcr` to schedule and trigger a recording.
- After recording, the video is sent to the computer and stored in current directory in /data.

```bash
pcr --help
```

#### Examples
- Start at a given epoch microseconds and record 5 seconds on ultra‑wide:
```bash
pcr --start-epoch-us 1757685000000000 --duration-s 5 --lens ultra-wide
```

- Start now + 2s (Linux bash):
```bash
now_us=$(($(date +%s%3N)*1000)); start_us=$((now_us + 2*1000000)); \
pcr --start-epoch-us "$start_us" --duration-s 3
```
