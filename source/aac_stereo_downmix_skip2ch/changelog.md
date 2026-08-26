# Changelog

## 0.0.6 (2026-08-26)

- Performance: library scan no longer runs a full loudness measurement pass per file - it now only checks the (cheap) normalize tag and defers actual measurement to worker time, roughly halving the wait on files with force re-encode enabled.
- Changed the normalize tag from an opaque settings hash to a plain presence marker (UNMANIC_AAC_NORMALIZE_SKIP2CH=1). Once a stream is tagged normalized, it is now permanently skipped on all future runs, even if loudnorm_formula or downmix_formula are changed afterward - avoids a second lossy re-encode of already-normalized audio. To force a re-check, the tag must be removed from the file manually.
- Loudness measurement start/result logs are now visible at info level instead of debug, so the multi-minute worker pause during measurement shows activity in Unmanic's log instead of appearing stuck.

## 0.0.5 (2026-08-25)

- Fixed: a stream that measures within loudness tolerance during a force re-encode check is now tagged as normalized (stream copy + metadata write, no audio re-encode) so it's correctly skipped on future runs. Previously it was left untagged and would be re-measured every run indefinitely.
- Safety: guarded against a missing/None absolute stream index from ffprobe, falling back to a safe re-encode instead of risking a mismatched tag-only skip or a broken ffmpeg map argument.
- Robustness: split timeout vs. general failures in the loudness measurement subprocess call for clearer debug logging; added a returncode check that still attempts to parse loudnorm stats before giving up.
- Cleanup: removed dead duplicate return paths in the loudness/tag decision logic; introduced a LOUDNORM_TARGET_LUFS constant so the measurement target and the default loudnorm formula's stated target are visibly tied together.

## 0.0.4

- Added stream metadata tagging: after a stream is encoded, a fingerprint of the current loudnorm/downmix settings is written to it as a custom tag. On future runs with force re-encode enabled, streams already tagged with a matching fingerprint are skipped without running a loudness measurement pass at all. Changing the loudnorm or downmix formula settings invalidates old tags automatically, so previously-tagged files are correctly reprocessed under new settings.

## 0.0.3

- Added optional "force re-encode" setting to check loudness on already-AAC mono/stereo streams and only re-encode if they're off-target, with a configurable tolerance (measured via an ffmpeg loudnorm analysis pass); labeled with a warning that this adds a full extra pass per stream and can slow down large libraries significantly
- Restored icon reference to original upstream source

## 0.0.2

- Consolidated logic into a single ffmpeg pass to avoid double-encoding audio that was previously handled by a separate downstream "Audio Encoder AAC" plugin
- Now correctly skips only streams that are already AAC and <=2 channels; non-AAC mono/stereo streams are encoded to AAC with loudnorm instead of being left untouched
- Fixed loudnorm filter being hardcoded to stream index a:0 regardless of which stream was actually being encoded, which caused "Filtergraph was specified but codec copy was selected" errors on multi-track files
- Sample rate is now only capped to 48kHz when the source exceeds it; lower source rates are left unchanged rather than being forced upward

## 0.0.1

- initial version
