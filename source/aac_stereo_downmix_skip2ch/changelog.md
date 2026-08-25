# Changelog

## 0.0.2 (2026-08-25)

- Consolidated logic into a single ffmpeg pass to avoid double-encoding audio that was previously handled by a separate downstream "Audio Encoder AAC" plugin
- Now correctly skips only streams that are already AAC and <=2 channels; non-AAC mono/stereo streams are encoded to AAC with loudnorm instead of being left untouched
- Fixed loudnorm filter being hardcoded to stream index a:0 regardless of which stream was actually being encoded, which caused "Filtergraph was specified but codec copy was selected" errors on multi-track files
- Sample rate is now only capped to 48kHz when the source exceeds it; lower source rates are left unchanged rather than being forced upward
- Added optional "force re-encode" setting to normalize/loudnorm every audio stream regardless of existing codec or channel count

## 0.0.1

- initial version
