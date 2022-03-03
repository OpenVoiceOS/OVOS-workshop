# Copyright 2019 Mycroft AI Inc.
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
#
from enum import IntEnum
from os.path import join, isfile

from ovos_utils import ensure_mycroft_import
ensure_mycroft_import()

from mycroft.enclosure.gui import SkillGUI as _SkillGUI
from mycroft.util import resolve_resource_file
from mycroft.messagebus.message import Message
from ovos_utils import resolve_ovos_resource_file


class SkillGUI(_SkillGUI):
    """SkillGUI - Interface to the Graphical User Interface

    Values set in this class are synced to the GUI, accessible within QML
    via the built-in sessionData mechanism.  For example, in Python you can
    write in a skill:
        self.gui['temp'] = 33
        self.gui.show_page('Weather.qml')
    Then in the Weather.qml you'd access the temp via code such as:
        text: sessionData.time
    """
    # new gui templates
    # TODO PR in mycroft-core, taken from gez-mycroft wifi GUI test skill
    def show_confirmation_status(self, text="", override_idle=False,
                                 override_animations=False):
        self.clear()
        self["icon"] = resolve_ovos_resource_file("ui/icons/check-circle.svg")
        self["label"] = text
        self["bgColor"] = "#40DBB0"
        self.show_page("SYSTEM_status.qml", override_idle=override_idle,
                       override_animations=override_animations)

    def show_error_status(self, text="", override_idle=False,
                          override_animations=False):
        self.clear()
        self["icon"] = resolve_ovos_resource_file("ui/icons/times-circle.svg")
        self["label"] = text
        self["bgColor"] = "#FF0000"
        self.show_page("SYSTEM_status.qml", override_idle=override_idle,
                       override_animations=override_animations)

    # everything above is a new method, everything below is partial overrides
    # these unfortunately require implementing the full method, may get out
    # of sync over time
    def show_pages(self, page_names, index=0, override_idle=None,
                   override_animations=False):
        """Begin showing the list of pages in the GUI.

        OVOS change: look for bundled ovos resources files

        Arguments:
            page_names (list): List of page names (str) to display, such as
                               ["Weather.qml", "Forecast.qml", "Details.qml"]
            index (int): Page number (0-based) to show initially.  For the
                         above list a value of 1 would start on "Forecast.qml"
            override_idle (boolean, int):
                True: Takes over the resting page indefinitely
                (int): Delays resting page for the specified number of
                       seconds.
            override_animations (boolean):
                True: Disables showing all platform skill animations.
                False: 'Default' always show animations.
        """
        if not isinstance(page_names, list):
            raise ValueError('page_names must be a list')

        if index > len(page_names):
            raise ValueError('Default index is larger than page list length')

        # First sync any data...
        data = self.__session_data.copy()
        data.update({'__from': self.skill.skill_id})
        if self.skill:
            self.skill.bus.emit(Message("gui.value.set", data))

        # Convert pages to full reference
        page_urls = []
        page = None
        for name in page_names:

            if name.startswith("SYSTEM"):
                page = resolve_resource_file(join('ui', name))
            elif self.skill:
                page = self.skill.find_resource(name, 'ui')

            if not page:
                # override to look for bundled pages
                page = resolve_ovos_resource_file(join('ui', name)) or \
                        resolve_ovos_resource_file(name)
            if page:
                if self.config.get('remote'):
                    page_urls.append(self.remote_url + "/" + page)
                else:
                    page_urls.append("file://" + page)
            else:
                raise FileNotFoundError("Unable to find page: {}".format(name))
        if self.skill:
            self.skill.bus.emit(Message("gui.page.show",
                                        {"page": page_urls,
                                         "index": index,
                                         "__from": self.skill.skill_id,
                                         "__idle": override_idle,
                                         "__animations": override_animations}))

    def remove_pages(self, page_names):
        """Remove a list of pages in the GUI.

        OVOS change: look for bundled ovos resources files

        Arguments:
            page_names (list): List of page names (str) to display, such as
                               ["Weather.qml", "Forecast.qml", "Other.qml"]
        """
        if not isinstance(page_names, list):
            raise ValueError('page_names must be a list')

        # Convert pages to full reference
        page_urls = []
        page = None
        for name in page_names:
            if name.startswith("SYSTEM"):
                page = resolve_resource_file(join('ui', name))
            elif self.skill:
                page = self.skill.find_resource(name, 'ui')

            if not page:
                # override to look for bundled pages
                page = resolve_ovos_resource_file(join('ui', name)) or \
                       resolve_ovos_resource_file(name)

            if page:
                page_urls.append("file://" + page)
            else:
                raise FileNotFoundError("Unable to find page: {}".format(name))
        if self.skill:
            self.skill.bus.emit(Message("gui.page.delete",
                                        {"page": page_urls,
                                         "__from": self.skill.skill_id}))
