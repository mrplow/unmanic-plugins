#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    unmanic-plugins.plugin.py

    Written by:               k29t59dh <chapels.rill_0h@icloud.com>
    Modified by:               mrplow

    Copyright:
        Copyright (C) 2021 Josh Sunnex

        This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
        Public License as published by the Free Software Foundation, version 3.

        This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
        implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
        for more details.

        You should have received a copy of the GNU General Public License along with this program.
        If not, see <https://www.gnu.org/licenses/>.

"""

import logging, os, subprocess, re, json

from unmanic.libs.unplugins.settings import PluginSettings
from aac_stereo_downmix_skip2ch.lib.ffmpeg import StreamMapper, Probe, Parser

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.aac_stereo_downmix_skip2ch")

# Metadata tag key/value written to processed audio streams. A stream carrying this tag
# is considered permanently normalized by this plugin - it will be skipped on all future
# runs regardless of whether loudnorm_formula/downmix_formula settings change later.
# This is intentional: re-normalizing an already-normalized AAC stream means a second
# lossy encode (generational loss) for no audible benefit, so tags are NOT invalidated
# by settings changes. To force a stream to be re-checked, its tag must be removed
# manually (e.g. by remuxing without this plugin, or with a separate script).
NORMALIZE_TAG_KEY = 'UNMANIC_AAC_NORMALIZE_SKIP2CH'
NORMALIZE_TAG_VALUE = '1'

# Target integrated loudness used for measurement comparisons during force re-encode checks.
# NOTE: kept as a constant here since 'loudnorm_formula' is a free-text setting - if a
# user changes the I= value in their formula, this constant won't automatically follow it.
LOUDNORM_TARGET_LUFS = -24.0


def measure_integrated_loudness(abspath, absolute_stream_index, timeout=600):
    """
    Runs a single ffmpeg analysis pass (no output file written) to measure a stream's
    current integrated loudness in LUFS, using the same loudnorm filter that would be
    used to encode it. Uses the stream's absolute ffprobe index to select it directly
    via '-map 0:{index}', avoiding any need to track audio-relative stream counters
    separately (since '-map 0:{index}' pulls in exactly one stream, it always becomes
    output stream a:0 regardless of its original position in the file).

    Returns the measured value as a float, or None if measurement failed or couldn't be
    parsed from ffmpeg's output.
    """
    if absolute_stream_index is None:
        logger.info("No absolute stream index available for '{}' - cannot measure loudness.".format(abspath))
        return None

    logger.info("Measuring loudness for stream index {} of '{}'...".format(absolute_stream_index, abspath))

    cmd = [
        'ffmpeg', '-hide_banner', '-nostats',
        '-i', abspath,
        '-map', '0:{}'.format(absolute_stream_index),
        '-filter:a:0', 'loudnorm=I={}:LRA=7.0:TP=-2.0:print_format=json'.format(LOUDNORM_TARGET_LUFS),
        '-f', 'null', '-',
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.info("Loudness measurement timed out after {}s for '{}'".format(timeout, abspath))
        return None
    except Exception as e:
        logger.info("Loudness measurement failed to run for '{}': {}".format(abspath, e))
        return None

    stderr = result.stderr.decode('utf-8', errors='ignore')

    if result.returncode != 0:
        logger.debug(
            "Loudness measurement ffmpeg process exited with code {} for '{}'".format(result.returncode, abspath)
        )
        # Still attempt to parse below - loudnorm sometimes prints stats before a late
        # non-fatal warning bumps the exit code. If parsing fails too, we'll return None.

    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr, re.DOTALL)
    if not match:
        logger.info("Could not find loudnorm JSON stats in ffmpeg output for '{}'".format(abspath))
        return None

    try:
        stats = json.loads(match.group(0))
        measured = float(stats.get('input_i'))
        logger.info("Measured loudness {} LUFS for '{}'".format(measured, abspath))
        return measured
    except (ValueError, TypeError) as e:
        logger.info("Could not parse loudnorm JSON stats for '{}': {}".format(abspath, e))
        return None


class Settings(PluginSettings):
    settings = {
        "force_reencode":     False,
        "loudness_tolerance": "1.0",
        "loudnorm_formula":   "loudnorm=I=-24.0:LRA=7.0:TP=-2.0",
        "downmix_formula":    "pan=stereo|c0=c2+0.30*c0+0.30*c4|c1=c2+0.30*c1+0.30*c5",
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.form_settings = {
            "force_reencode": {
                "label": "Always check already-AAC mono/stereo streams for loudness, even if codec/channels are fine "
                         "(WARNING: for streams not already tagged as normalized by this plugin, this adds a full "
                         "extra ffmpeg measurement pass per stream at worker time. This can significantly slow down "
                         "processing on large libraries. Once a stream is tagged as normalized, it is PERMANENTLY "
                         "skipped on all future runs, even if you change the formulas below - this avoids a second "
                         "lossy re-encode. To force a re-check, the tag must be removed from the file manually.)",
            },
            "loudness_tolerance": {
                "label": "Loudness tolerance in LU (only used when force re-encode is on, and only for streams not "
                         "already tagged as normalized). How far a stream's measured loudness can be from the -24 "
                         "LUFS target before it's re-encoded. As a rough guide: ~1 LU is generally the smallest "
                         "difference most listeners can perceive, ~3 LU is a clearly noticeable difference, ~5+ LU "
                         "is a large, obvious difference. A lower tolerance re-encodes more files (more accurate, "
                         "more processing time); a higher tolerance skips more files (faster, allows more loudness "
                         "drift).",
            },
            "loudnorm_formula": {
                "label": "Loudnorm filter (applied to every encoded stream)",
            },
            "downmix_formula": {
                "label": "Downmix filter (applied before loudnorm when source has >2 channels)",
            },
        }


class PluginStreamMapper(StreamMapper):
    def __init__(self):
        super(PluginStreamMapper, self).__init__(logger, ['audio'])
        self.encoder = 'aac'
        self.settings = None
        self.abspath = None
        # If False, skip the expensive ffmpeg loudness measurement pass entirely and just
        # assume a not-yet-tagged stream needs processing. Used during the library scan
        # phase (on_library_management_file_test), where we only need a yes/no answer for
        # queuing and the actual measurement would be run again anyway at worker time.
        self.allow_measurement = True
        # Tracks streams that measured within tolerance during force_reencode checks -
        # these get tagged-but-copied in custom_stream_mapping rather than re-encoded.
        # Keyed by absolute ffprobe stream index. Reset per-file in set_default_values.
        self.tag_only_streams = set()

    def set_default_values(self, settings, abspath, probe, allow_measurement=True):
        self.abspath = abspath
        self.set_probe(probe)
        self.set_input_file(abspath)
        self.settings = settings
        self.allow_measurement = allow_measurement
        self.tag_only_streams = set()

    @staticmethod
    def __get_stream_tags(stream_info: dict):
        tags = stream_info.get('tags', {}) or {}
        # ffprobe tag key casing can vary by container - normalize to lowercase for lookup
        return {str(k).lower(): v for k, v in tags.items()}

    def __is_tagged_normalized(self, stream_info: dict):
        tags = self.__get_stream_tags(stream_info)
        return tags.get(NORMALIZE_TAG_KEY.lower()) == NORMALIZE_TAG_VALUE

    def test_stream_needs_processing(self, stream_info: dict):
        channels = stream_info.get('channels', 2)
        codec_name = stream_info.get('codec_name', '').lower()

        already_aac_and_stereo_or_less = channels <= 2 and codec_name == 'aac'

        if not already_aac_and_stereo_or_less:
            # Codec conversion or downmix is needed regardless of loudness - no point
            # spending time measuring, it's getting re-encoded either way.
            return True

        if not self.settings.get_setting('force_reencode'):
            # Already AAC + <=2ch, and we're not checking loudness on "fine" files - skip.
            return False

        # Already AAC + <=2ch, force_reencode is on. If this stream is already tagged as
        # normalized, it's permanently skipped - no re-check, no re-measurement, ever,
        # regardless of current formula settings.
        if self.__is_tagged_normalized(stream_info):
            logger.debug(
                "Stream already tagged as normalized for '{}' - skipping permanently.".format(self.abspath)
            )
            return False

        if not self.allow_measurement:
            # Library-scan phase: don't run the expensive measurement pass here, just
            # queue the file. The real measurement (and tag-only vs re-encode decision)
            # happens once, for real, when the worker actually processes this file.
            logger.debug(
                "Skipping loudness measurement during scan for '{}' - not yet tagged, deferring to worker.".format(
                    self.abspath
                )
            )
            return True

        absolute_stream_index = stream_info.get('index')
        if absolute_stream_index is None:
            # Can't reliably measure or correlate this stream without its index -
            # re-encode to be safe rather than risk a mismatched tag-only skip.
            logger.debug(
                "Stream has no absolute index reported by ffprobe for '{}' - re-encoding to be safe.".format(
                    self.abspath
                )
            )
            return True

        measured = measure_integrated_loudness(self.abspath, absolute_stream_index)
        if measured is None:
            # Measurement failed - re-encode to be safe rather than silently skipping
            # a file we couldn't verify.
            return True

        try:
            tolerance = float(self.settings.get_setting('loudness_tolerance'))
        except (TypeError, ValueError):
            tolerance = 1.0

        needs_reencode = abs(measured - LOUDNORM_TARGET_LUFS) > tolerance
        logger.debug(
            "Measured loudness {} LUFS for '{}' (target {}, tolerance {}) - {}".format(
                measured, self.abspath, LOUDNORM_TARGET_LUFS, tolerance,
                "re-encoding" if needs_reencode else "already within tolerance, tagging only"
            )
        )

        if not needs_reencode:
            # Already within tolerance - no need to re-encode audio, but custom_stream_mapping
            # still needs to run so it can stamp the tag and permanently avoid re-checking.
            self.tag_only_streams.add(absolute_stream_index)

        return True

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
        absolute_stream_index = stream_info.get('index')
        is_tag_only = absolute_stream_index is not None and absolute_stream_index in self.tag_only_streams

        if is_tag_only:
            # Stream already measured as within tolerance - just copy it and stamp the
            # tag, no re-encode needed. Avoids pointless generational loss on a file
            # that's already normalized.
            return {
                'stream_mapping':  ['-map', '0:a:{}'.format(stream_id)],
                'stream_encoding': [
                    '-c:a:{}'.format(stream_id), 'copy',
                    '-metadata:s:a:{}'.format(stream_id),
                    '{}={}'.format(NORMALIZE_TAG_KEY, NORMALIZE_TAG_VALUE),
                ],
            }

        channels = stream_info.get('channels', 2)
        sample_rate = int(stream_info.get('sample_rate', 48000))

        loudnorm_formula = self.settings.get_setting('loudnorm_formula')
        downmix_formula = self.settings.get_setting('downmix_formula')

        if channels > 2:
            filter_formula = '{},{}'.format(downmix_formula, loudnorm_formula)
        else:
            filter_formula = loudnorm_formula

        stream_encoding = [
            '-c:a:{}'.format(stream_id), self.encoder,
            '-filter:a:{}'.format(stream_id), filter_formula,
        ]

        if sample_rate > 48000:
            stream_encoding += ['-ar:a:{}'.format(stream_id), '48000']

        stream_encoding += [
            '-metadata:s:a:{}'.format(stream_id),
            '{}={}'.format(NORMALIZE_TAG_KEY, NORMALIZE_TAG_VALUE),
        ]

        return {
            'stream_mapping':  ['-map', '0:a:{}'.format(stream_id)],
            'stream_encoding': stream_encoding,
        }


def on_library_management_file_test(data):
    abspath = data.get('path')

    probe = Probe(logger, allowed_mimetypes=['audio', 'video'])
    if not probe.file(abspath):
        return data

    if data.get('library_id'):
        settings = Settings(library_id=data.get('library_id'))
    else:
        settings = Settings()

    mapper = PluginStreamMapper()
    # Don't run the expensive loudness measurement during scanning - just queue anything
    # not already tagged, and let the worker do the real measurement once.
    mapper.set_default_values(settings, abspath, probe, allow_measurement=False)

    if mapper.streams_need_processing():
        data['add_file_to_pending_tasks'] = True
        logger.debug("File '{}' should be added to task list. Probe found streams require processing.".format(abspath))
    else:
        logger.debug("File '{}' does not contain streams require processing.".format(abspath))

    return data


def on_worker_process(data):
    data['exec_command'] = []
    data['repeat'] = False

    abspath = data.get('file_in')

    probe = Probe(logger, allowed_mimetypes=['audio', 'video'])
    if not probe.file(abspath):
        return data

    settings = Settings(library_id=data.get('library_id'))

    mapper = PluginStreamMapper()
    mapper.set_default_values(settings, abspath, probe, allow_measurement=True)

    if mapper.streams_need_processing():
        mapper.set_input_file(abspath)
        mapper.set_output_file(data.get('file_out'))

        ffmpeg_args = mapper.get_ffmpeg_args()

        data['exec_command'] = ['ffmpeg']
        data['exec_command'] += ffmpeg_args

        parser = Parser(logger)
        parser.set_probe(probe)
        data['command_progress_parser'] = parser.parse_progress

    return data
