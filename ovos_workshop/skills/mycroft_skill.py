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
"""Common functionality relating to the implementation of mycroft skills."""

import shutil
from abc import ABCMeta
from os.path import join, exists

from ovos_config.locations import get_xdg_config_save_path
from ovos_utils.log import LOG

from ovos_workshop.skills.base import BaseSkill


def is_classic_core():
    """ Check if the current core is the classic mycroft-core """
    try:
        from mycroft.version import OVOS_VERSION_STR
        return False
    except ImportError:
        return True


class _SkillMetaclass(ABCMeta):
    """ To override isinstance checks we need to use a metaclass """

    def __instancecheck__(self, instance):
        if is_classic_core():
            # instance imported from vanilla mycroft
            try:
                from mycroft.skills import MycroftSkill as _CoreSkill
                if issubclass(self.__class__, _CoreSkill):
                    return True
            except ImportError:
                # not running in core - standalone skill
                pass

            # instance imported from workshop
            # we can not patch mycroft-core class to make isinstance return True

        return super().__instancecheck__(instance)


class MycroftSkill(BaseSkill, metaclass=_SkillMetaclass):
    """Base class for mycroft skills providing common behaviour and parameters
    to all Skill implementations.

    For information on how to get started with creating mycroft skills see
    https://mycroft.ai/documentation/skills/introduction-developing-skills/

    New methods added here are always private, public apis for Skill class are added in OVOSSkill
    This is done to ensure no syntax errors when a MycroftSkill object comes from mycroft-core

    Args:
        name (str): skill name
        bus (MycroftWebsocketClient): Optional bus connection
        use_settings (bool): Set to false to not use skill settings at all (DEPRECATED)
    """

    def __init__(self, name=None, bus=None, use_settings=True, *args, **kwargs):
        super().__init__(name=name, bus=bus, *args, **kwargs)

        self._initial_settings = {}
        self.settings_write_path = None
        self.settings_manager = None

        # old kludge from fallback skills, unused according to grep
        if use_settings is False:
            LOG.warning("use_settings has been deprecated! skill settings are always enabled")

        if is_classic_core():
            self.settings_write_path = self.root_dir

    def _init_settings_manager(self):
        try:
            from mycroft.skills.settings import SkillSettingsManager
            from mycroft.deprecated.skills.settings import SettingsMetaUploader
            self.settings_manager = SkillSettingsManager(self)
            # backwards compat - self.settings_meta has been deprecated in favor of settings manager
            self._settings_meta = SettingsMetaUploader(self.root_dir, self.skill_id)
        except ImportError:
            pass

    def _init_settings(self):
        """Setup skill settings."""
        # migrate settings if needed
        if not exists(self._settings_path) and exists(self._old_settings_path):
            LOG.warning("Found skill settings at pre-xdg location, migrating!")
            shutil.copy(self._old_settings_path, self._settings_path)
            LOG.info(f"{self._old_settings_path} moved to {self._settings_path}")

        super()._init_settings()

    # renamed in base class for naming consistency
    def init_dialog(self, root_directory=None):
        """ DEPRECATED: use load_dialog_files instead """
        self.load_dialog_files(root_directory)

    # renamed in base class for naming consistency
    def make_active(self):
        """Bump skill to active_skill list in intent_service.

        This enables converse method to be called even without skill being
        used in last 5 minutes.

        deprecated: use self.activate() instead
        """
        self._activate()

    # patched due to functional (internal) differences under mycroft-core
    def _on_event_end(self, message, handler_info, skill_data):
        """Store settings and indicate that the skill handler has completed
        """
        if not is_classic_core():
            return super()._on_event_end(message, handler_info, skill_data)

        # mycroft-core style settings
        if self.settings != self._initial_settings:
            try:
                from mycroft.skills.settings import save_settings
                save_settings(self.settings_write_path, self.settings)
                self._initial_settings = dict(self.settings)
            except Exception as e:
                LOG.exception("Failed to save skill settings")
        if handler_info:
            msg_type = handler_info + '.complete'
            message.context["skill_id"] = self.skill_id
            self.bus.emit(message.forward(msg_type, skill_data))

    # renamed in base class for naming consistency
    # refactored to use new resource utils
    def translate(self, text, data=None):
        """Deprecated method for translating a dialog file.
        use self._resources.render_dialog(text, data) instead"""
        return self._resources.render_dialog(text, data)

    # renamed in base class for naming consistency
    # refactored to use new resource utils
    def translate_namedvalues(self, name, delim=','):
        """Deprecated method for translating a name/value file.
        use elf._resources.load_named_value_filetext, data) instead"""
        return self._resources.load_named_value_file(name, delim)

    # renamed in base class for naming consistency
    # refactored to use new resource utils
    def translate_list(self, list_name, data=None):
        """Deprecated method for translating a list.
        use delf._resources.load_list_file(text, data) instead"""
        return self._resources.load_list_file(list_name, data)

    # renamed in base class for naming consistency
    # refactored to use new resource utils
    def translate_template(self, template_name, data=None):
        """Deprecated method for translating a template file
        use delf._resources.template_file(text, data) instead"""
        return self._resources.load_template_file(template_name, data)

    # refactored - backwards compat + log warnings
    @property
    def settings_meta(self):
        LOG.warning("self.settings_meta has been deprecated! please use self.settings_manager instead")
        return self._settings_meta

    # refactored - backwards compat + log warnings
    @settings_meta.setter
    def settings_meta(self, val):
        LOG.warning("self.settings_meta has been deprecated! please use self.settings_manager instead")
        self._settings_meta = val

    # internal - deprecated under ovos-core
    @property
    def _old_settings_path(self):
        old_dir = self.config_core.get("data_dir") or "/opt/mycroft"
        old_folder = self.config_core.get("skills", {}).get("msm", {}) \
                         .get("directory") or "skills"
        return join(old_dir, old_folder, self.skill_id, 'settings.json')

    # patched due to functional (internal) differences under mycroft-core
    @property
    def _settings_path(self):
        if self.settings_write_path and self.settings_write_path != self.root_dir:
            LOG.warning("self.settings_write_path has been deprecated! "
                        "Support will be dropped in a future release")
            return join(self.settings_write_path, 'settings.json')
        return super()._settings_path
