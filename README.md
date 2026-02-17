# Phone Camera Recorder (Android + Desktop CLI)

This project provides:
- An Android app that records video controlled via desktop, starting at an exact epoch‑microseconds timestamp for a fixed duration.
- A cross‑platform desktop CLI (Windows/Linux) that schedules and triggers the recording via ADB.
- Tested on Samsung S23 and S25, with Ubuntu and Windows hosts.

## Android phone setup
1) Enable Developer options on the phone:
	- Settings -> About phone -> Software information -> tap Build number 7 times
2) Enable USB debugging in Developer options.
3) Connect the phone to the computer via USB.
4) (Optional but advised) Enable Stay awake in Developer options.

## Desktop prerequisites
1) Install Android Platform Tools (`adb`) on the computer:
	- https://developer.android.com/tools/releases/platform-tools
2) Install JDK 17+ (required for building the Android app with Gradle): https://www.oracle.com/java/technologies/downloads/
3) Ensure Android SDK components are available (platform/build-tools), or build through Android Studio.
4) Verify device connectivity:
	- `adb version`
	- `adb devices`
	- Accept the phone's USB debugging authorization prompt.

## Desktop CLI setup
### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./desktop-cli
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .\desktop-cli
```

## Install Android app on phone
> Note: `gradlew` / `gradlew.bat` is the Gradle Wrapper script included in this repo. You do not install Gradle separately for this project.

### Linux

```bash
cd android-app
./gradlew installDebug
```

### Windows (PowerShell)

```powershell
cd android-app
.\gradlew.bat installDebug
```

If you need manual APK installation instead of `installDebug`:

- Linux: `adb install -r app/build/outputs/apk/debug/app-debug.apk`
- Windows: `adb install -r app\build\outputs\apk\debug\app-debug.apk`

## Usage
- Use `pcr` to schedule and trigger a recording.
- Output is pulled to host directory `./data` by default.
- Override destination with `--pull-to <dir>` or environment variable `PCR_DATA_DIR`.

```bash
pcr --help
```

### Examples
- Start at a given epoch microseconds and record 5 seconds on ultra‑wide:

```bash
pcr --start-epoch-us 1757685000000000 --duration-s 5 --lens ultra-wide
```

- Start now + 2s (Linux bash):

```bash
now_us=$(($(date +%s%3N)*1000)); start_us=$((now_us + 2*1000000)); \
pcr --start-epoch-us "$start_us" --duration-s 3
```

- Start now + 2s (Windows PowerShell):

```powershell
$nowUs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() * 1000
$startUs = $nowUs + 2*1000000
pcr --start-epoch-us $startUs --duration-s 3
```
