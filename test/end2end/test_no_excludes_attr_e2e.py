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
"""Real-bus end-to-end regression guard for the OVOS-INTENT-4 §5.2
``excluded`` field: a skill whose adapt ``Intent`` parser object has no
``excludes`` attribute (the shape of the legacy ``adapt-parser`` package,
which predates the exclude concept) must still register and match, because
``excluded`` is spec-optional (absent = ``[]``).

Boots a real (mini) OVOS stack via ovoscope's ``MiniCroft`` and loads the
``no_excludes_test_skill`` fixture, exercising the real
``register_intent`` -> ``munge_intent_parser`` -> ``_emit_spec_keyword_intent``
path that raised ``AttributeError`` before the fix.
"""
import sys
from os.path import dirname

import pytest

from ovoscope import get_minicroft

from ovos_bus_client.session import SessionManager
from ovos_spec_tools import SpecMessage

sys.path.insert(0, dirname(__file__))

SKILL_ID = "no.excludes.e2e.test"


def _boot():
    from no_excludes_test_skill import NoExcludesTestSkill
    return get_minicroft([SKILL_ID],
                         extra_skills={SKILL_ID: NoExcludesTestSkill},
                         modernize=False, emit_legacy=False)


def _of_type(mc, msg_type):
    return [(m.data, m.context) for m in mc.boot_messages
            if m.msg_type == str(msg_type)]


class TestNoExcludesAttrE2E:
    mc = None

    @classmethod
    def setup_class(cls):
        from ovos_utils.log import LOG
        LOG.set_level("ERROR")
        cls._saved_bus = SessionManager.bus
        cls.mc = _boot()

    @classmethod
    def teardown_class(cls):
        cls.mc.stop()
        SessionManager.bus = cls._saved_bus

    def test_keyword_intent_without_excludes_registers(self):
        """Loading the fixture skill must not raise, and the spec keyword
        payload's ``excluded`` key must resolve to an empty list."""
        kw = _of_type(self.mc, SpecMessage.INTENT_REGISTER_KEYWORD)
        assert len(kw) == 1
        data, _ = kw[0]
        assert data["excluded"] == []

    def test_legacy_register_intent_still_flows(self):
        """The dual-emitted legacy ``register_intent`` (consumed by the real
        adapt pipeline plugin to build its matcher) also flowed, proving the
        skill's intent is actually live on the bus, not just the spec
        payload."""
        assert len(_of_type(self.mc, "register_intent")) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
