"""
CLI to schedule and trigger video recording on an Android phone via adb.
"""

import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

PACKAGE = "nl.tudelft.pcr"
ACTIVITY = "nl.tudelft.pcr/.MainActivity"


def _default_data_dir() -> str:
    # Default based on repo layout; env override is provided via --pull-to envvar (PCR_DATA_DIR)
    here = Path(__file__).resolve()
    for p in list(here.parents):
        if (
            (p / ".git").exists()
            and (p / "android-app").exists()
            and (p / "desktop-cli").exists()
        ):
            return str(p / "data")
    # Fallback: parent that contains both android-app and desktop-cli
    for p in list(here.parents):
        if (p / "android-app").exists() and (p / "desktop-cli").exists():
            return str(p / "data")
    # Last resort: current working directory
    return str(Path.cwd() / "data")


DEFAULT_PULL_TO = _default_data_dir()


def run_adb(args):
    """Run an adb command with given args and return stdout; exits on error."""
    try:
        result = subprocess.run(
            ["adb", *args], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        click.echo(f"PHONE-CAMERA-RECORDER: {e.stdout}")
        click.echo(f"PHONE-CAMERA-RECORDER: {e.stderr}", err=True)
        sys.exit(e.returncode)


def get_device_time_epoch_us():
    """Get the current device time in epoch microseconds."""
    out = run_adb(["shell", "date +%s%3N"])  # milliseconds
    ms = int(out)
    return ms * 1000


def host_time_epoch_us():
    """Get the current host time in epoch microseconds."""
    return int(time.time() * 1_000_000)


def ensure_device():
    """Ensure an adb device is connected and authorized."""
    out = run_adb(["get-state"])  # returns 'device' when ready
    if out.strip() != "device":
        click.echo(
            "PHONE-CAMERA-RECORDER: No adb device ready. "
            "Run 'adb devices' and ensure it's authorized.",
            err=True,
        )
        sys.exit(1)


def schedule_delay_us(start_epoch_us, offset_us):
    """Calculate delay on host to align device recording start time."""
    now_host_us = host_time_epoch_us()
    # Compensate host->device offset: device_time = host_time + offset_us
    # We start intent so that device receives close to desired device time
    intended_host_us = start_epoch_us - offset_us
    delay_us = intended_host_us - now_host_us
    return max(delay_us, 0)


@click.command()
@click.option(
    "--start-epoch-us",
    type=int,
    required=True,
    help="Start time in epoch microseconds (device time)",
)
@click.option("--duration-s", type=float, required=True, help="Duration in seconds")
@click.option(
    "--lens", type=click.Choice(["ultra-wide", "back", "front"]), default="ultra-wide"
)
@click.option(
    "--package", default=PACKAGE, show_default=True, help="Android app package"
)
@click.option(
    "--pull-to",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=True),
    envvar="PCR_DATA_DIR",
    default=DEFAULT_PULL_TO,
    show_default=True,
    help="Directory on host to store pulled videos (can be set via PCR_DATA_DIR or this flag)",
)
@click.option("--no-audio", is_flag=True, help="Disable audio recording")
def main(start_epoch_us, duration_s, lens, package, pull_to, no_audio):
    """
    click main
    """
    pcr_main(start_epoch_us, duration_s, lens, package, pull_to, no_audio)


def pcr_main(
    start_epoch_us: int,
    duration_s: float,
    lens: str,
    package: str = PACKAGE,
    pull_to: Path = Path(DEFAULT_PULL_TO),
    no_audio: bool = True,
) -> tuple[bool, Path | None, Path | None]:
    """Schedule a video recording on a connected Android phone.

    The Android app must be installed and exposes an intent that starts
    recording at the given epoch microseconds for the given duration.
    """

    ensure_device()
    # Clear logcat so we only see new events
    run_adb(["logcat", "-c"])

    duration_ms = int(duration_s * 1000)

    # Determine host->device clock offset (device_us - host_us)
    device_us = get_device_time_epoch_us()
    host_us = host_time_epoch_us()
    offset_us = device_us - host_us

    delay_us = schedule_delay_us(start_epoch_us, offset_us)

    # Print start time info
    start_dt = datetime.fromtimestamp(start_epoch_us / 1_000_000, tz=timezone.utc)
    click.echo(
        f"PHONE-CAMERA-RECORDER: Scheduled start time: {start_epoch_us} (epoch μs)"
    )
    click.echo(
        f"PHONE-CAMERA-RECORDER: Scheduled start time: "
        f"{start_dt.strftime('%Y-%m-%d %H:%M:%S.%f %Z')}"
    )
    click.echo(f"PHONE-CAMERA-RECORDER: Duration: {duration_s:.3f} seconds")

    if delay_us > 0:
        click.echo(
            f"PHONE-CAMERA-RECORDER: Waiting {delay_us / 1e6:.3f}s to align start…"
        )
        time.sleep(delay_us / 1_000_000)

    # Launch activity with typed extras to avoid shell quoting issues
    cmd = [
        "shell",
        "am",
        "start",
        "-n",
        f"{package}/.MainActivity",
        "--el",
        "pcr_start_epoch_us",
        str(start_epoch_us),
        "--ei",
        "pcr_duration_ms",
        str(duration_ms),
        "--es",
        "pcr_lens",
        lens,
        "--ez",
        "pcr_trigger",
        "true",
    ]
    if no_audio:
        cmd.extend(["--ez", "pcr_no_audio", "true"])
    click.echo("PHONE-CAMERA-RECORDER: Starting recording via intent…")
    run_adb(cmd)
    click.echo("PHONE-CAMERA-RECORDER: Intent sent. Waiting for device to finalize…")

    # Wait for finalize messages and saved file paths, retrying logcat fetch if needed
    pattern_video = re.compile(r"PCR_SAVED path=(.+)")
    pattern_ts = re.compile(r"PCR_SAVED_TS path=(.+)")
    deadline = time.time() + max(10, duration_ms / 1000 + 10)
    saved_path = None
    saved_ts_path = None
    last_log = ""
    while time.time() < deadline and (saved_path is None or saved_ts_path is None):
        # Always fetch the latest logs
        out = run_adb(["logcat", "-d", "-s", "PCR/Main"])
        if out != last_log:
            for line in out.splitlines():
                if saved_path is None:
                    m = pattern_video.search(line)
                    if m:
                        saved_path = m.group(1).strip()
                if saved_ts_path is None:
                    m2 = pattern_ts.search(line)
                    if m2:
                        saved_ts_path = m2.group(1).strip()
            last_log = out
        if saved_path is None or saved_ts_path is None:
            time.sleep(0.5)

    if not saved_path:
        click.echo(
            "PHONE-CAMERA-RECORDER: Did not see saved file path in logs; "
            "recording may have failed. If the file is present on the phone, "
            "you can pull it manually.",
            err=True,
        )
        return False, None, None

    Path(pull_to).mkdir(parents=True, exist_ok=True)
    host_path: Path | None = Path(pull_to) / Path(saved_path).name
    click.echo(f"PHONE-CAMERA-RECORDER: Pulling video to {host_path} …")
    pull_result = run_adb(["pull", saved_path, str(host_path)])
    click.echo(f"PHONE-CAMERA-RECORDER: {pull_result}")
    if host_path and host_path.exists():
        click.echo(f"PHONE-CAMERA-RECORDER: Saved: {host_path}")
    else:
        click.echo(
            f"PHONE-CAMERA-RECORDER: Tried to pull {saved_path} but file not found on host. "
            f"Check device path and permissions.",
            err=True,
        )
        host_path = None

    # If we found a timestamp file, pull it as well
    host_ts_path: Path | None = None
    if saved_ts_path:
        host_ts_path = Path(pull_to) / Path(saved_ts_path).name
        click.echo(f"PHONE-CAMERA-RECORDER: Pulling timestamps to {host_ts_path} …")
        pull_ts_result = run_adb(["pull", saved_ts_path, str(host_ts_path)])
        click.echo(f"PHONE-CAMERA-RECORDER: {pull_ts_result}")
        if host_ts_path and host_ts_path.exists():
            click.echo(f"PHONE-CAMERA-RECORDER: Saved timestamps: {host_ts_path}")
        else:
            click.echo(
                f"PHONE-CAMERA-RECORDER: Tried to pull {saved_ts_path} but "
                f"file not found on host.",
                err=True,
            )
            host_ts_path = None
    else:
        # Fallback: infer .txt next to the mp4 and pull if present
        guess_ts = re.sub(r"\.mp4$", ".txt", saved_path)
        probe = run_adb(
            [
                "shell",
                "if",
                "[",
                "-f",
                guess_ts,
                "];",
                "then",
                "echo",
                "EXISTS;",
                "else",
                "echo",
                "MISSING;",
                "fi",
            ]
        )
        if "EXISTS" in probe:
            host_ts_path = Path(pull_to) / Path(guess_ts).name
            click.echo(
                f"PHONE-CAMERA-RECORDER: Pulling timestamps (inferred) to {host_ts_path} …"
            )
            pull_ts_result = run_adb(["pull", guess_ts, str(host_ts_path)])
            click.echo(f"PHONE-CAMERA-RECORDER: {pull_ts_result}")
            if host_ts_path and host_ts_path.exists():
                click.echo(f"PHONE-CAMERA-RECORDER: Saved timestamps: {host_ts_path}")
            else:
                click.echo(
                    f"PHONE-CAMERA-RECORDER: Tried to pull {guess_ts} but "
                    f"file not found on host.",
                    err=True,
                )
                host_ts_path = None
        else:
            click.echo(
                "PHONE-CAMERA-RECORDER: No timestamp file reported by logs and none "
                "found next to the mp4; skipping timestamps pull."
            )
            host_ts_path = None

    return (host_path is not None), host_path, host_ts_path
