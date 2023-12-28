# Copyright 2020 Mycroft AI Inc.
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

from typing import Dict, Optional
from ovos_bus_client.message import Message
from ovos_utils.log import LOG


class SkillApi:
    """
    SkillApi provides a MessageBus interface to specific registered methods.
    Methods decorated with `@skill_api_method` are exposed via the messagebus.
    To use a skill's API methods, call `SkillApi.get` with the requested skill's
    ID and an object is returned with an interface to all exposed methods.
    """
    bus = None

    @classmethod
    def connect_bus(cls, mycroft_bus):
        """Registers the bus object to use."""
        cls.bus = mycroft_bus

    def __init__(self, method_dict: Dict[str, dict], timeout: int = 3):
        """
        Initialize a SkillApi for the given methods
        @param method_dict: dict of method name to dict containing:
            `help` - method docstring
            `type` - string Message type associated with this method
        @param timeout: Seconds to wait for a Skill API response
        """
        self.method_dict = method_dict
        self.timeout = timeout
        for key in method_dict:
            def get_method(k):
                def method(*args, **kwargs):
                    m = self.method_dict[k]
                    data = {'args': args, 'kwargs': kwargs}
                    method_msg = Message(m['type'], data)
                    response = \
                        SkillApi.bus.wait_for_response(method_msg,
                                                       timeout=self.timeout)
                    if not response:
                        LOG.error(f"Timed out waiting for {method_msg}")
                        return None
                    elif 'result' not in response.data:
                        LOG.error(f"missing `result` in: {response.data}")
                    else:
                        return response.data['result']

                return method

            self.__setattr__(key, get_method(key))

    @staticmethod
    def get(skill: str, api_timeout: int = 3) -> Optional[object]:
        """
        Generate a SkillApi object for the requested skill if that skill exposes
        and API methods.
        @param skill: ID of skill to get an API object for
        @param api_timeout: seconds to wait for a skill API response
        @return: SkillApi object if available, else None
        """
        if not SkillApi.bus:
            raise RuntimeError("Requested update before `SkillAPI.bus` is set. "
                               "Call `SkillAPI.connect_bus` first.")
        public_api_msg = f'{skill}.public_api'
        api = SkillApi.bus.wait_for_response(Message(public_api_msg))
        if api:
            return SkillApi(api.data, api_timeout)
        else:
            return None