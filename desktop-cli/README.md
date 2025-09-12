Desktop CLI (pcr)

Usage
- Ensure adb is installed and phone is connected with USB debugging enabled.
- Install the Android app APK on the phone.

Examples
- Start at a given epoch microseconds and record 5 seconds on ultra‑wide:
  pcr --start-epoch-us 1757685000000000 --duration-s 5 --lens ultra-wide

- Start now + 2s:
  $nowUs = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())*1000
  $startUs = $nowUs + 2*1000000
  pcr --start-epoch-us $startUs --duration-s 3

Notes
- The CLI syncs device/host time offset before scheduling.
- Start time is in DEVICE epoch microseconds.
