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


def measure_integrated_loudness(abspath, absolute_stream_index, timeout=600):
    """
    Runs a single ffmpeg analysis pass (no output file written) to measure a stream's
    current integrated loudness in LUFS, using the same loudnorm filter that would be
    used to encode it. Uses the stream's absolute ffprobe index (stream_info['index'])
    to select it directly via '-map 0:{index}', avoiding any need to track audio-relative
    stream counters separately (since '-map 0:{index}' pulls in exactly one stream, it
    always becomes output stream a:0 regardless of its original position in the file).
    Returns the measured value as a float, or None if measurement failed or couldn't be
    parsed from ffmpeg's output.
    """
    cmd = [
        'ffmpeg', '-hide_banner', '-nostats',
        '-i', abspath,
        '-map', '0:{}'.format(absolute_stream_index),
        '-filter:a:0', 'loudnorm=I=-24.0:LRA=7.0:TP=-2.0:print_format=json',
        '-f', 'null', '-',
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        stderr = result.stderr.decode('utf-8', errors='ignore')
        match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr, re.DOTALL)
        if not match:
            logger.debug("Could not find loudnorm JSON stats in ffmpeg output for '{}'".format(abspath))
            return None
        stats = json.loads(match.group(0))
        return float(stats.get('input_i'))
    except Exception as e:
        logger.debug("Loudness measurement failed for '{}': {}".format(abspath, e))
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
                         "(WARNING: this measures loudness on every already-compliant audio stream during library "
                         "scanning and worker processing, adding a full extra ffmpeg pass per stream even on files "
                         "that end up being skipped. This can significantly slow down scans and processing on large "
                         "libraries.)",
            },
            "loudness_tolerance": {
                "label": "Loudness tolerance in LU (only used when force re-encode is on). "
                         "How far a stream's measured loudness can be from the -24 LUFS target "
                         "before it's re-encoded. As a rough guide: ~1 LU is generally the "
                         "smallest difference most listeners can perceive, ~3 LU is a clearly "
                         "noticeable difference, ~5+ LU is a large, obvious difference. A lower "
                         "tolerance re-encodes more files (more accurate, more processing time); "
                         "a higher tolerance skips more files (faster, allows more loudness drift).",
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

    def set_default_values(self, settings, abspath, probe):
        self.abspath = abspath
        self.set_probe(probe)
        self.set_input_file(abspath)
        self.settings = settings

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

        # Already AAC + <=2ch, but force_reencode is on: only re-encode if loudness is
        # actually off-target, to avoid a pointless generational-loss re-encode of a
        # file that's already normalized.
        absolute_stream_index = stream_info.get('index')
        measured = measure_integrated_loudness(self.abspath, absolute_stream_index)
        if measured is None:
            # Measurement failed - fall back to re-encoding to be safe rather than
            # silently skipping a file we couldn't verify.
            return True

        try:
            tolerance = float(self.settings.get_setting('loudness_tolerance'))
        except (TypeError, ValueError):
            tolerance = 1.0

        target = -24.0
        needs_reencode = abs(measured - target) > tolerance
        logger.debug(
            "Measured loudness {} LUFS for '{}' (target {}, tolerance {}) - {}".format(
                measured, self.abspath, target, tolerance,
                "re-encoding" if needs_reencode else "skipping"
            )
        )
        return needs_reencode

    def custom_stream_mapping(self, stream_info: dict, stream_id: int):
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
    mapper.set_default_values(settings, abspath, probe)

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
    mapper.set_default_values(settings, abspath, probe)

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
