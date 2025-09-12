import subprocess
import sys
import time
import json
from datetime import datetime, timezone
import click
import os
import re

PACKAGE = "nl.tudelft.pcr"
ACTIVITY = "nl.tudelft.pcr/.MainActivity"


def run_adb(args):
    try:
        result = subprocess.run(["adb", *args], capture_output=True, text=True, check=True)
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
        click.echo("No adb device ready. Run 'adb devices' and ensure it's authorized.", err=True)
        sys.exit(1)


def schedule_delay_us(start_epoch_us, offset_us):
    now_host_us = host_time_epoch_us()
    # Compensate host->device offset: device_time = host_time + offset_us
    # We start intent so that device receives close to desired device time
    intended_host_us = start_epoch_us - offset_us
    delay_us = intended_host_us - now_host_us
    return max(delay_us, 0)


@click.command()
@click.option("--start-epoch-us", type=int, required=True, help="Start time in epoch microseconds (device time)")
@click.option("--duration-s", type=float, required=True, help="Duration in seconds")
@click.option("--lens", type=click.Choice(["ultra-wide", "back", "front"]), default="ultra-wide")
@click.option("--package", default=PACKAGE, show_default=True, help="Android app package")
@click.option("--pull-to", type=click.Path(file_okay=False, dir_okay=True, resolve_path=True), default=os.path.join(os.getcwd(), "data"), show_default=True, help="Directory on host to store pulled videos")
@click.option("--no-audio", is_flag=True, help="Disable audio recording")
def main(start_epoch_us, duration_s, lens, package, pull_to, no_audio):
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
        click.echo(f"Waiting {delay_us/1e6:.3f}s to align start…")
        time.sleep(delay_us / 1_000_000)

    # Launch activity with typed extras to avoid shell quoting issues
    cmd = [
        "shell",
        "am", "start",
        "-n", f"{package}/.MainActivity",
        "--el", "pcr_start_epoch_us", str(start_epoch_us),
        "--ei", "pcr_duration_ms", str(duration_ms),
        "--es", "pcr_lens", lens,
        "--ez", "pcr_trigger", "true",
    ]
    if no_audio:
        cmd.extend(["--ez", "pcr_no_audio", "true"])
    click.echo("Starting recording via intent…")
    run_adb(cmd)
    click.echo("Intent sent. Waiting for device to finalize…")


    # Wait for finalize message and saved file path, retrying logcat fetch if needed
    pattern = re.compile(r"PCR_SAVED path=(.+)")
    deadline = time.time() + max(10, duration_ms / 1000 + 10)
    saved_path = None
    last_log = ""
    while time.time() < deadline and saved_path is None:
        # Always fetch the latest logs
        out = run_adb(["logcat", "-d", "-s", "PCR/Main"])
        if out != last_log:
            for line in out.splitlines():
                m = pattern.search(line)
                if m:
                    saved_path = m.group(1).strip()
                    break
            last_log = out
        if saved_path is None:
            time.sleep(0.5)

    if not saved_path:
        click.echo("Did not see saved file path in logs; recording may have failed. If the file is present on the phone, you can pull it manually.", err=True)
        return

    os.makedirs(pull_to, exist_ok=True)
    host_path = os.path.join(pull_to, os.path.basename(saved_path))
    click.echo(f"Pulling video to {host_path} …")
    pull_result = run_adb(["pull", saved_path, host_path])
    click.echo(pull_result)
    if os.path.exists(host_path):
        click.echo(f"Saved: {host_path}")
    else:
        click.echo(f"Tried to pull {saved_path} but file not found on host. Check device path and permissions.", err=True)


if __name__ == "__main__":
    main()
