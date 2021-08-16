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
from ovos_workshop.patches.settings_gui_generator import SettingsGuiGenerator
from ovos_utils import resolve_ovos_resource_file
from ovos_utils.gui import _GUIDict

# implements the following GUI functionality
# https://github.com/MycroftAI/mycroft-core/pull/2698


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

    def __init__(self, skill):
        super().__init__(skill)
        self.__skills_config = {}  # data object passed to skill's page
        self.settings_gui_generator = SettingsGuiGenerator()

    # fix gui subdict sync TODO PR in mycroft-core
    def _sync_data(self):
        data = self.__session_data.copy()
        data.update({'__from': self.skill.skill_id})
        self.skill.bus.emit(Message("gui.value.set", data))

    def __setitem__(self, key, value):
        """Implements set part of dict-like behaviour with named keys."""

        # cast to helper dict subclass that syncs data
        if isinstance(value, dict) and not isinstance(value, _GUIDict):
            value = _GUIDict(self, **value)

        self.__session_data[key] = value

        # emit notification (but not needed if page has not been shown yet)
        if self.page:
            self._sync_data()

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

    # skill settings
    # https://github.com/MycroftAI/mycroft-core/pull/2698
    def register_settings(self):
        """Register requested skill settings
        configuration in GUI.

        Registers handler to apply settings when
        updated via GUI interface.
        Register handler to update settings when
        updated via Web interface.
        """
        skill_id = self.skill.skill_id

        settingmeta_path = join(self.skill.root_dir,
                                "settingsmeta.json")
        if isfile(settingmeta_path):
            self.settings_gui_generator.populate(skill_id,
                                                 settingmeta_path,
                                                 self.skill.settings)
            apply_handler = skill_id + ".settings.set"
            update_handler = skill_id + ".settings.update"
            remove_pagehandler = skill_id + ".settings.remove_page"
            self.register_handler(apply_handler,
                                  self._apply_settings)
            self.register_handler(update_handler,
                                  self._update_settings)
            self.register_handler(remove_pagehandler,
                                  self._remove_settings_display)

        else:
            raise FileNotFoundError("Unable to find setting file for: {}".
                                    format(skill_id))

    def show_settings(self, override_idle=True,
                      override_animations=False):
        """Display skill configuration page in GUI.

        Arguments:
        override_idle (boolean, int):
                True: Takes over the resting page indefinitely
                (int): Delays resting page for the specified number of
                       seconds.
        override_animations (boolean):
                True: Disables showing all platform skill animations.
                False: 'Default' always show animations.
        """
        self.clear()
        self.__skills_config["sections"] = self.settings_gui_generator.fetch()
        self.__skills_config["skill_id"] = self.skill.skill_id
        self["skillsConfig"] = self.__skills_config
        self.show_page("SYSTEM_SkillSettings.qml",
                       override_idle=override_idle)

    def _apply_settings(self, message):
        """Store updated values for keys in skill settings.

        Arguments:
        message: Messagebus message
        """
        self.skill.settings[message.data["setting_key"]] = \
            message.data["setting_value"]

    def _update_settings(self, message):
        """Update changed skill settings in GUI.

        Arguments:
        message: Messagebus message
        """
        self.clear()
        self.settings_gui_generator.update(self.skill.settings)
        self.show_settings()

    def _remove_settings_display(self, message):
        """Removes skill settings page from GUI.

        Arguments:
        message: Messagebus message
        """
        self.clear()
        self.remove_page("SYSTEM_SkillSettings.qml")

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

        self.page = page_names[index]

        # First sync any data...
        data = self.__session_data.copy()
        data.update({'__from': self.skill.skill_id})
        self.skill.bus.emit(Message("gui.value.set", data))

        # Convert pages to full reference
        page_urls = []
        for name in page_names:

            if name.startswith("SYSTEM"):
                page = resolve_resource_file(join('ui', name))
            else:
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
        for name in page_names:
            if name.startswith("SYSTEM"):
                page = resolve_resource_file(join('ui', name))
            else:
                page = self.skill.find_resource(name, 'ui')

            if not page:
                # override to look for bundled pages
                page = resolve_ovos_resource_file(join('ui', name)) or \
                       resolve_ovos_resource_file(name)

            if page:
                page_urls.append("file://" + page)
            else:
                raise FileNotFoundError("Unable to find page: {}".format(name))

        self.skill.bus.emit(Message("gui.page.delete",
                                    {"page": page_urls,
                                     "__from": self.skill.skill_id}))

