# Changelog

## 1.1.0

- Log the captured original modified date (in a readable format) during the worker stage, also visible in the live worker log tail.
- Log the restored modified date for each destination file, plus a summary, during the post-processor task results stage.

## 1.0.0

- Initial release.
- Capture the source file's mtime in the worker stage.
- Re-apply the captured mtime to all destination files in the task-results stage.
