# Copyright 2026 OpenVoiceOS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Fixture skill for the OVOS-INTENT-4 §5.2 no-``excludes``-attribute
regression test: registers a real adapt keyword intent whose parser object
has no ``excludes`` attribute at all, matching the shape of the legacy
``adapt-parser`` package's ``Intent`` class (which predates the exclude
concept)."""
from ovos_workshop.intents import IntentBuilder
from ovos_workshop.skills.ovos import OVOSSkill


class NoExcludesTestSkill(OVOSSkill):
    """Registers one adapt keyword intent via a parser object stripped of
    its ``excludes`` attribute, then handles a matching utterance."""

    def initialize(self):
        self.register_vocabulary("play", "playKW")
        self.register_vocabulary("song", "songKW")

        intent = IntentBuilder("play_song").require("playKW").require("songKW").build()
        del intent.excludes
        self.register_intent(intent, self.handle_play_song)

    def handle_play_song(self, message):
        self.bus.emit(message.reply("no_excludes.e2e.test.handled"))


def create_skill():
    return NoExcludesTestSkill()
