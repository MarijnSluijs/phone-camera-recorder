import json
import os
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
    # Env override first
    env_dir = os.environ.get("PCR_DATA_DIR")
    if env_dir:
        return str(Path(env_dir).expanduser())
    # Try to locate repo root based on this file's path (works best in editable installs)
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
    try:
        result = subprocess.run(
            ["adb", *args], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        click.echo(e.stdout)
        click.echo(e.stderr, err=True)
        sys.exit(e.returncode)


def get_device_time_epoch_us():
    out = run_adb(["shell", "date +%s%3N"])  # milliseconds
    ms = int(out)
    return ms * 1000


def host_time_epoch_us():
    return int(time.time() * 1_000_000)


def ensure_device():
    out = run_adb(["get-state"])  # returns 'device' when ready
    if out.strip() != "device":
        click.echo(
            "No adb device ready. Run 'adb devices' and ensure it's authorized.",
            err=True,
        )
        sys.exit(1)


def schedule_delay_us(start_epoch_us, offset_us):
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
    default=DEFAULT_PULL_TO,
    show_default=True,
    help="Directory on host to store pulled videos (override with PCR_DATA_DIR env or this flag)",
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
    pull_to: Path = DEFAULT_PULL_TO,
    no_audio: bool = True,
):
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
    click.echo(f"Scheduled start time: {start_epoch_us} (epoch μs)")
    click.echo(f"Scheduled start time: {start_dt.strftime('%Y-%m-%d %H:%M:%S.%f %Z')}")
    click.echo(f"Duration: {duration_s:.3f} seconds")

    if delay_us > 0:
        click.echo(f"Waiting {delay_us / 1e6:.3f}s to align start…")
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
    click.echo("Starting recording via intent…")
    run_adb(cmd)
    click.echo("Intent sent. Waiting for device to finalize…")

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
            "Did not see saved file path in logs; recording may have failed. If the file is present on the phone, you can pull it manually.",
            err=True,
        )
        return

    os.makedirs(pull_to, exist_ok=True)
    host_path = os.path.join(pull_to, os.path.basename(saved_path))
    click.echo(f"Pulling video to {host_path} …")
    pull_result = run_adb(["pull", saved_path, host_path])
    click.echo(pull_result)
    if os.path.exists(host_path):
        click.echo(f"Saved: {host_path}")
    else:
        click.echo(
            f"Tried to pull {saved_path} but file not found on host. Check device path and permissions.",
            err=True,
        )

    # If we found a timestamp file, pull it as well
    if saved_ts_path:
        host_ts_path = os.path.join(pull_to, os.path.basename(saved_ts_path))
        click.echo(f"Pulling timestamps to {host_ts_path} …")
        pull_ts_result = run_adb(["pull", saved_ts_path, host_ts_path])
        click.echo(pull_ts_result)
        if os.path.exists(host_ts_path):
            click.echo(f"Saved timestamps: {host_ts_path}")
        else:
            click.echo(
                f"Tried to pull {saved_ts_path} but file not found on host.", err=True
            )
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
            host_ts_path = os.path.join(pull_to, os.path.basename(guess_ts))
            click.echo(f"Pulling timestamps (inferred) to {host_ts_path} …")
            pull_ts_result = run_adb(["pull", guess_ts, host_ts_path])
            click.echo(pull_ts_result)
            if os.path.exists(host_ts_path):
                click.echo(f"Saved timestamps: {host_ts_path}")
            else:
                click.echo(
                    f"Tried to pull {guess_ts} but file not found on host.", err=True
                )
        else:
            click.echo(
                "No timestamp file reported by logs and none found next to the mp4; skipping timestamps pull."
            )
