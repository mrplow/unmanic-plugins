# Changelog

## 0.0.3 (2026-08-25)

- Added optional "force re-encode" setting to check loudness on already-AAC mono/stereo streams and only re-encode if they're off-target, with a configurable tolerance (measured via an ffmpeg loudnorm analysis pass); labeled with a warning that this adds a full extra pass per stream and can slow down large libraries significantly

## 0.0.2 (2026-08-25)

- Consolidated logic into a single ffmpeg pass to avoid double-encoding audio that was previously handled by a separate downstream "Audio Encoder AAC" plugin
- Now correctly skips only streams that are already AAC and <=2 channels; non-AAC mono/stereo streams are encoded to AAC with loudnorm instead of being left untouched
- Fixed loudnorm filter being hardcoded to stream index a:0 regardless of which stream was actually being encoded, which caused "Filtergraph was specified but codec copy was selected" errors on multi-track files
- Sample rate is now only capped to 48kHz when the source exceeds it; lower source rates are left unchanged rather than being forced upward
- Restored icon reference to original upstream source

## 0.0.1

- initial version
