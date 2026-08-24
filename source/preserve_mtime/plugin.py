#!/usr/bin/env python3
"""
plugin.py

Preserve Original Modified Date
--------------------------------
Captures the mtime (and atime) of a source file before it is processed by
Unmanic, then re-applies those timestamps to the resulting output file(s)
once the task has completed successfully.

Runners used:
    on_worker_process               - capture the source file's mtime/atime
    on_postprocessor_task_results   - apply the captured mtime/atime to the
                                       final destination file(s)
"""
import logging
import os
from datetime import datetime

from unmanic.libs.unplugins.settings import PluginSettings
from unmanic.libs.task import TaskDataStore

logger = logging.getLogger("Unmanic.Plugin.preserve_mtime")

# Key used to store the captured timestamps in the task-scoped data store
TASK_STATE_KEY = "preserve_mtime.timestamps"


def _human_readable(epoch_timestamp):
    """
    Format a UNIX epoch timestamp as a readable local date/time string,
    keeping the raw epoch value alongside it for anyone cross-checking logs.

    :param epoch_timestamp:
    :return:
    """
    try:
        return "{} (epoch {})".format(
            datetime.fromtimestamp(epoch_timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            epoch_timestamp,
        )
    except (OSError, OverflowError, ValueError):
        return "epoch {}".format(epoch_timestamp)


class Settings(PluginSettings):
    """
    An object to hold a dictionary of settings accessible to the Plugin
    class and configurable by users from within the Unmanic WebUI.
    """
    settings = {
        "Enable mtime preservation": True,
    }


def on_worker_process(
    data,
    task_data_store: type[TaskDataStore] | None = None,
):
    """
    Runner function - captures the original source file's mtime/atime just
    before Unmanic executes the worker command against it.

    The 'data' object argument includes:
        task_id                 - Integer, unique identifier of the task.
        worker_log              - Array, log lines tailed by the frontend.
        library_id               - Number, the library associated with the task.
        exec_command             - Array, subprocess command Unmanic should execute.
        command_progress_parser  - Function used to parse command STDOUT.
        file_in                  - String, source file to be processed.
        file_out                 - String, destination the command should output to.
        original_file_path       - String, absolute path to the original file.
        repeat                   - Boolean, should this runner run again.

    :param data:
    :param task_data_store:
    :return:
    """
    settings = Settings(library_id=data.get('library_id'))
    if not settings.get_setting('Enable mtime preservation'):
        return

    original_file_path = data.get('original_file_path')
    if not original_file_path or not os.path.exists(original_file_path):
        logger.debug("Original file path not found - skipping mtime capture: '%s'", original_file_path)
        return

    try:
        stat_result = os.stat(original_file_path)
    except OSError as e:
        logger.warning("Unable to stat original file '%s' - %s", original_file_path, e)
        return

    if task_data_store is None:
        logger.warning("Task data store helper unavailable - unable to carry mtime through to post-processing")
        return

    # Only capture once per task. If this runner executes again (eg. 'repeat'),
    # keep the very first captured value rather than overwriting it with a
    # later (already-modified) intermediate cache file's timestamp.
    existing = task_data_store.get_task_state(TASK_STATE_KEY)
    if existing:
        logger.debug("Original mtime already captured for this task - skipping re-capture")
        return

    task_data_store.set_task_state(TASK_STATE_KEY, {
        "mtime": stat_result.st_mtime,
        "atime": stat_result.st_atime,
    })

    readable_mtime = _human_readable(stat_result.st_mtime)
    log_line = "Preserve Original Modified Date - captured original modified date {} for '{}'".format(
        readable_mtime, original_file_path,
    )
    logger.info(log_line)
    # Also surface this in the worker's live log tail in the WebUI
    worker_log = data.get('worker_log')
    if worker_log is not None:
        worker_log.append("\n{}".format(log_line))

    return


def on_postprocessor_task_results(
    data,
    task_data_store: type[TaskDataStore] | None = None,
):
    """
    Runner function - re-applies the captured mtime/atime to every
    destination file created for this task, once it has completed
    successfully.

    The 'data' object argument includes:
        library_id                   - The library associated with the task.
        task_id                      - Integer, unique identifier of the task.
        task_type                    - String, "local" or "remote".
        final_cache_path             - String, path to the final cache file.
        task_processing_success      - Boolean, did all task processes succeed.
        file_move_processes_success  - Boolean, did all postprocessor moves succeed.
        destination_files            - List of all file paths created by postprocessor.
        source_data                  - Dictionary of data on the original source file.
        start_time                   - Float, UNIX timestamp task began.
        finish_time                  - Float, UNIX timestamp task completed.

    :param data:
    :param task_data_store:
    :return:
    """
    settings = Settings(library_id=data.get('library_id'))
    if not settings.get_setting('Enable mtime preservation'):
        return

    if not data.get('task_processing_success'):
        logger.debug("Task did not complete successfully - not applying mtime")
        return

    if task_data_store is None:
        logger.warning("Task data store helper unavailable - unable to read captured mtime")
        return

    stored = task_data_store.get_task_state(TASK_STATE_KEY)
    if not stored or 'mtime' not in stored:
        logger.debug("No captured mtime found for this task - nothing to apply")
        return

    mtime = stored['mtime']
    atime = stored.get('atime', mtime)
    readable_mtime = _human_readable(mtime)

    destination_files = data.get('destination_files') or []
    if not destination_files:
        logger.debug("No destination files were reported for this task - nothing to apply")
        return

    updated_count = 0
    for destination_file in destination_files:
        if not os.path.exists(destination_file):
            logger.warning("Destination file does not exist, cannot set mtime: '%s'", destination_file)
            continue
        try:
            os.utime(destination_file, (atime, mtime))
            updated_count += 1
            logger.info(
                "Preserve Original Modified Date - restored original modified date %s on '%s'",
                readable_mtime, destination_file,
            )
        except OSError as e:
            logger.warning("Failed to set mtime on '%s' - %s", destination_file, e)

    if updated_count:
        logger.info(
            "Preserve Original Modified Date - completed. Applied original modified date %s to %d file(s)",
            readable_mtime, updated_count,
        )

    return
