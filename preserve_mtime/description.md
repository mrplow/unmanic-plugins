Transcoding or converting a file normally resets its filesystem "modified" timestamp (mtime) to the moment the new file was written.

This plugin records the original source file's mtime right before a task is processed, then re-applies that exact mtime to the resulting output file(s) once the task has finished successfully — so `stat`/`ls -l` and any tools that rely on modified-date (media managers, sync tools, "recently added" sorts, etc.) continue to see the original date instead of "today".

### How it works

1. **Worker stage** — before Unmanic processes the file, the plugin reads the original file's mtime and stores it against the task.
2. **Task results stage** — after the task completes successfully, the plugin applies that stored mtime to every destination file Unmanic created.

### Settings

- **Enable mtime preservation** — toggle the plugin on/off without removing it from your library's plugin flow.
