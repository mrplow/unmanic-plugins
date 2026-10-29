import time

from unmanic.libs.unplugins.settings import PluginSettings
from unmanic.libs.unplugins.child_process import PluginChildProcess


class Settings(PluginSettings):
    settings = {
        "delay_minutes": 5,
    }

    form_settings = {
        "delay_minutes": {
            "label": "Delay before processing",
            "description": "Number of minutes to wait before Unmanic continues processing this file. Set to 0 to disable.",
            "input_type": "slider",
            "slider_options": {
                "min": 0,
                "max": 120,
                "step": 1,
                "suffix": " minutes",
            },
        },
    }


def wait_for_delay(delay_seconds, source_path, log_queue=None, prog_queue=None):
    """Wait for the configured duration while reporting progress."""

    start_time = time.monotonic()
    last_log_time = -10

    log_queue.put(
        "Waiting {:.1f} minutes before processing: {}".format(
            delay_seconds / 60, source_path
        )
    )

    prog_queue.put(0)

    while True:
        elapsed = time.monotonic() - start_time
        remaining = max(0, delay_seconds - elapsed)

        percent = min(100, int((elapsed / delay_seconds) * 100))
        prog_queue.put(percent)

        if int(elapsed) // 10 > last_log_time // 10:
            last_log_time = int(elapsed)
            minutes = int(remaining) // 60
            seconds = int(remaining) % 60

            log_queue.put(
                "Processing delay: {:02d}:{:02d} remaining".format(
                    minutes, seconds
                )
            )

        if remaining <= 0:
            break

        time.sleep(min(1, remaining))

    prog_queue.put(100)
    log_queue.put("Processing delay complete. Continuing with file.")


def on_worker_process(data):
    settings = Settings(library_id=data.get("library_id"))

    try:
        delay_minutes = float(settings.get_setting("delay_minutes") or 0)
    except (TypeError, ValueError):
        delay_minutes = 5

    delay_minutes = max(0, delay_minutes)

    if delay_minutes <= 0:
        return data

    delay_seconds = delay_minutes * 60

    process = PluginChildProcess(
        plugin_id="worker_processing_delay",
        data=data,
    )

    success = process.run(
        wait_for_delay,
        delay_seconds,
        data.get("file_in", ""),
    )

    if not success:
        raise RuntimeError("The processing delay did not complete successfully.")

    return data
