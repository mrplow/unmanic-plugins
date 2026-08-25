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

import logging, os

from unmanic.libs.unplugins.settings import PluginSettings
from aac_stereo_downmix_skip2ch.lib.ffmpeg import StreamMapper, Probe, Parser

# Configure plugin logger
logger = logging.getLogger("Unmanic.Plugin.aac_stereo_downmix_skip2ch")


class Settings(PluginSettings):
    settings = {
        "force_reencode":   False,
        "loudnorm_formula": "loudnorm=I=-24.0:LRA=7.0:TP=-2.0",
        "downmix_formula":  "pan=stereo|c0=c2+0.30*c0+0.30*c4|c1=c2+0.30*c1+0.30*c5",
    }

    def __init__(self, *args, **kwargs):
        super(Settings, self).__init__(*args, **kwargs)
        self.form_settings = {
            "force_reencode": {
                "label": "Always re-encode and normalize, even if stream is already AAC mono/stereo",
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

    def set_default_values(self, settings, abspath, probe):
        self.abspath = abspath
        self.set_probe(probe)
        self.set_input_file(abspath)
        self.settings = settings

    def test_stream_needs_processing(self, stream_info: dict):
        if self.settings.get_setting('force_reencode'):
            return True

        channels = stream_info.get('channels', 2)
        codec_name = stream_info.get('codec_name', '').lower()

        if channels <= 2 and codec_name == 'aac':
            return False

        return True

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
