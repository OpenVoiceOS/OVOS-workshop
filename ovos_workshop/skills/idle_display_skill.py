# Copyright 2021 Mycroft AI Inc.
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
"""Provide a common API for skills that define idle screen functionality.

The idle display should show when no other skill is using the display.  Some
skills use the display for a defined period of time before returning to the
idle display (e.g. Weather Skill).  Some skills take control of the display
indefinitely (e.g. Timer Skill).

The display could be a touch screen (such as on the Mark II), or an
Arduino LED array (such as on the Mark I), or any other type of display.  This
base class is meant to be agnostic to the type of display, with the
implementation details defined within the skill that uses this as a base class.
"""
from ovos_utils.messagebus import Message
from ovos_workshop.patches.base_skill import MycroftSkill
from ovos_utils.log import LOG


class IdleDisplaySkill(MycroftSkill):
    """Base class for skills that define an idle display.

    An idle display is what shows on a device's screen when it is not in use
    by other skills.  For example, Mycroft's Home Screen Skill.
    """
    def __init__(self, *args, **kwargs):
        super(IdleDisplaySkill, self).__init__(*args, **kwargs)
        self._homescreen_entry = None

    def bind(self, bus):
        """Tasks to complete during skill load but after bus initialization."""
        if bus:
            super().bind(bus)
            self._define_message_bus_handlers()
            self._build_homscreen_entry()

    def _define_message_bus_handlers(self):
        """Defines the bus events handled in this skill and their handlers."""
        self.add_event("mycroft.ready", self.handle_mycroft_ready)
        self.add_event("homescreen.manager.activate.display", self._display_homescreen_requested)
        self.add_event("homescreen.manager.reload.list", self._reload_homescreen_entry)
        self.add_event("mycroft.skills.shutdown", self._remove_homescreen_on_shutdown)

    def handle_mycroft_ready(self, _):
        """Shows idle screen when device is ready for use."""
        self._show_idle_screen()
        self.bus.emit(Message("skill.idle.displayed"))
        LOG.debug("Homescreen ready")

    def _show_idle_screen(self):
        """Override this method to display the idle screen."""
        raise NotImplementedError(
            "Subclass must override the _show_idle_screen method"
        )

    def _build_homscreen_entry(self):
        # get the super class this inherits from
        super_class_name = "IdleDisplaySkill"
        super_class_object = self.__class__.__name__
        self._homescreen_entry = {"class": super_class_name,
                                  "name": super_class_object ,
                                  "id": self.skill_id}
        self._add_available_homescreen()

    def _add_available_homescreen(self):
        LOG.debug(f"Registering Homescreen {self._homescreen_entry}")
        self.bus.emit(Message("homescreen.manager.add", self._homescreen_entry))

    def _remove_homescreen(self):
        LOG.debug(f"Requesting removal of {self._homescreen_entry}")
        self.bus.emit(Message("homescreen.manager.remove", self._homescreen_entry))

    def _reload_homescreen_entry(self, _):
        self._build_homscreen_entry()

    def _remove_homescreen_on_shutdown(self, _):
        shutdown_for_id = _.data["id"]
        if shutdown_for_id == self.skill_id:
            LOG.debug("Requesting Homescreen shutdown")
            self._remove_homescreen()

    def _display_homescreen_requested(self, _):
        request_for_id = _.data["homescreen_id"]
        if request_for_id == self.skill_id:
            self._show_idle_screen()
            self.bus.emit(Message("skill.idle.displayed"))
