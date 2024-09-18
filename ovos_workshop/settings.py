import json
from os.path import isfile
from threading import Timer
from typing import Optional

import yaml
from json_database import JsonStorageXDG

from ovos_backend_client.api import DeviceApi
from ovos_backend_client.pairing import is_paired, requires_backend
from ovos_backend_client.settings import RemoteSkillSettings, get_display_name
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_utils.log import LOG


class SkillSettingsManager:
    def __init__(self, skill):
        self.download_timer: Optional[Timer] = None
        self.skill = skill
        self.api = DeviceApi()
        self.remote_settings = \
            RemoteSkillSettings(self.skill_id,
                                settings=dict(self.skill.settings),
                                meta=self.load_meta(), remote_id=self.skill_gid)
        self.register_bus_handlers()

    def start(self):
        self._download()

    def _download(self):
        # If this method is called outside of the timer loop, ensure the
        # existing timer is canceled before starting a new one.
        if self.download_timer:
            self.download_timer.cancel()

        self.download()

        # prepare to download again in 60 seconds
        self.download_timer = Timer(60, self._download)
        self.download_timer.daemon = True
        self.download_timer.start()

    def stop(self):
        # If this method is called outside of the timer loop, ensure the
        # existing timer is canceled
        if self.download_timer:
            self.download_timer.cancel()

    @property
    def bus(self) -> MessageBusClient:
        return self.skill.bus

    @property
    def skill_id(self) -> str:
        return self.skill.skill_id

    @property
    def display_name(self) -> str:
        return get_display_name(self.skill_id)

    @property
    def skill_gid(self) -> str:
        return f"@{self.api.uuid}|{self.skill_id}"

    @property
    def skill_meta(self) -> dict:
        return self.remote_settings.meta

    def register_bus_handlers(self):
        self.skill.add_event('mycroft.skills.settings.update',
                             self.handle_download_remote)  # backwards compat
        self.skill.add_event('mycroft.skills.settings.download',
                             self.handle_download_remote)
        self.skill.add_event('mycroft.skills.settings.upload',
                             self.handle_upload_local)
        self.skill.add_event('mycroft.skills.settings.upload.meta',
                             self.handle_upload_meta)
        self.skill.add_event('mycroft.paired',
                             self.handle_upload_local)

    def load_meta(self) -> dict:
        json_path = f"{self.skill.root_dir}/settingsmeta.json"
        yaml_path = f"{self.skill.root_dir}/settingsmeta.yaml"
        if isfile(yaml_path):
            with open(yaml_path) as meta_file:
                return yaml.safe_load(meta_file)
        elif isfile(json_path):
            with open(json_path) as meta_file:
                return json.load(meta_file)
        return {}

    def save_meta(self, generate: bool = False):
        # unset reload flag to avoid a reload on settingmeta change
        # TODO - support for settingsmeta XDG paths
        reload = self.skill.reload_skill
        self.skill.reload_skill = False

        # generate meta for missing fields
        if generate:
            self.remote_settings.generate_meta()

        # write to disk
        json_path = f"{self.skill.root_dir}/settingsmeta.json"
        yaml_path = f"{self.skill.root_dir}/settingsmeta.yaml"
        if isfile(yaml_path):
            with open(yaml_path) as meta_file:
                yaml.dump(self.remote_settings.meta, meta_file)
        else:
            with open(json_path, "w") as meta_file:
                json.dump(self.remote_settings.meta, meta_file)

        # reset reloading flag
        self.skill.reload_skill = reload

    @requires_backend
    def upload(self, generate: bool = False):
        if not is_paired():
            LOG.error("Device needs to be paired to upload settings")
            return
        self.remote_settings.settings = dict(self.skill.settings)
        if generate:
            self.remote_settings.generate_meta()
        self.remote_settings.upload()

    @requires_backend
    def upload_meta(self, generate: bool = False):
        if not is_paired():
            LOG.error("Device needs to be paired to upload settingsmeta")
            return
        if generate:
            self.remote_settings.settings = dict(self.skill.settings)
            self.remote_settings.generate_meta()
        self.remote_settings.upload_meta()

    @requires_backend
    def download(self):
        if not is_paired():
            LOG.error("Device needs to be paired to download remote settings")
            return
        self.remote_settings.download()
        # we do not update skill object settings directly
        # skill will handle the event and trigger a callback
        if self.skill.settings != self.remote_settings.settings:
            # dig old message to keep context
            msg = dig_for_message() or Message("")
            msg = msg.forward('mycroft.skills.settings.changed')

            msg.data[self.skill_id] = self.remote_settings.settings
            self.bus.emit(msg)

    def handle_upload_meta(self, message: Message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.upload_meta()

    def handle_upload_local(self, message: Message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.upload()

    def handle_download_remote(self, message: Message):
        self.download()


def settings2meta(settings, section_name="Skill Settings"):
    """ generates basic settingsmeta """
    fields = []

    for k, v in settings.items():
        if k.startswith("_"):
            continue
        label = k.replace("-", " ").replace("_", " ").title()
        if isinstance(v, bool):
            fields.append({
                "name": k,
                "type": "checkbox",
                "label": label,
                "value": str(v).lower()
            })
        if isinstance(v, str):
            fields.append({
                "name": k,
                "type": "text",
                "label": label,
                "value": v
            })
        if isinstance(v, int):
            fields.append({
                "name": k,
                "type": "number",
                "label": label,
                "value": str(v)
            })
    return {
        "skillMetadata": {
            "sections": [
                {
                    "name": section_name,
                    "fields": fields
                }
            ]
        }
    }


class PrivateSettings(JsonStorageXDG):
    def __init__(self, skill_id):
        super(PrivateSettings, self).__init__(skill_id)

    @property
    def settingsmeta(self):
        return settings2meta(self, self.name)
