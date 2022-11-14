import itertools
import time
import typing
from enum import Enum
from threading import Event
from typing import Any, Dict, Optional, Sequence, Tuple, Union
from uuid import uuid4

from mycroft_bus_client import Message
from ovos_utils.log import LOG
from ovos_utils.sound import play_audio

from ovos_workshop.skills.ovos import OVOSSkill

SessionDialogDataType = Optional[Dict[str, Any]]
SessionDialogType = Union[str, Tuple[str, SessionDialogDataType]]
SessionDialogsType = Union[SessionDialogType, Sequence[SessionDialogType]]

SessionGuiDataType = Optional[Dict[str, Any]]
SessionGuiType = Union[str, Tuple[str, SessionGuiDataType]]
SessionGuisType = Union[SessionGuiType, Sequence[SessionGuiType]]





class DeDinkumFier:
    def __init__(self, skill_folder):
        self.path = skill_folder
        with open(f"{self.path}/__init__.py") as f:
            self.code = f.read()

    @property
    def is_dinkum(self):
        if "def create_skill(skill_id:" in self.code and "def __init__(self, skill_id" in self.code:
            return True
        return False

    def fix(self):
        if not self.is_dinkum:
            raise RuntimeError("Not a dinkum skill!")
        if "MycroftSkill" not in self.code:
            raise ValueError("MycroftSkill class import not found")
        self.fix_skill_id_init()
        self.fix_imports()

    def fix_skill_id_init(self):
        self.code = self.code.replace("skill_id: str", "skill_id=''")

    def fix_imports(self):
        lines = self.code.split("\n")
        import_start = 0
        for idx, l in enumerate(lines):
            if "import" in l and not import_start:
                import_start = idx
            if "from mycroft.skills import" in l:
                l = l.replace(" MycroftSkill", "").replace(",,", ",").\
                    replace(" GuiClear", "").replace(",,", ",").replace("import,", "import")
                if l.strip().endswith(" import"):
                    l = ""
                lines[idx] = l
            else:
                lines[idx] = lines[idx].replace("MycroftSkill", "UnDinkumSkill")
        lines.insert(import_start, "from ovos_workshop.skills.dinkum import GuiClear, UnDinkumSkill")


class SkillControl:
    """
    the SkillControl class is used by the
    system to make skills conform to
    system level requirements.

    state - is used by the skill itself to
    manage its behavior. currently the
    system does not look at a skill's
    state (though this could change
    in the future) and there are no state
    values defined at the system level.

    states - is a dict keyed by skill state
    of intent lists. it is only used by the
    change_state() method to enable/disable
    intents based on the skill's state.

    category - the category defines the skill
    category. skill categories are used by
    the system to manage intent priority.
    for example, during converse, skills of
    category 'system' are given preference.
    old style skills do not use any of this
    and are assigned a default category of
    'undefined' during instantiation. As a
    result, currently the system only recognizes
    the 'undefined' category and the 'system'
    category. This is done intentionally
    to not restrict the use of category by
    skills for other purposes at a later date.


    default values to be overidden
    by the skill constructor in its
    constructor.
    """

    state = "inactive"
    states = None
    category = "undefined"


class GuiClear(str, Enum):
    AUTO = "auto"
    ON_IDLE = "on_idle"
    NEVER = "never"
    AT_START = "at_start"
    AT_END = "at_end"


class MessageSend(str, Enum):
    AT_START = "at_start"
    AT_END = "at_end"


class UnDinkumSkill(OVOSSkill):
    def __init__(self, skill_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skill_service_initializing = False
        self.skill_control = SkillControl()

        # Unique id generated for every started/ended
        self._activity_id: str = ""

        # Session id from last speak()
        self._tts_session_id: typing.Optional[str] = None
        self._tts_speak_finished = Event()

        if self.bus and skill_id:
            self._startup(self.bus, skill_id=skill_id)

    def change_state(self, new_state):
        """change skill state to new value.
        does nothing except log a warning
        if the new state is invalid"""
        self.log.debug(
            "change_state() skill:%s - changing state from %s to %s"
            % (self.skill_id, self.skill_control.state, new_state)
        )

        if self.skill_control.states is None:
            return

        if new_state not in self.skill_control.states:
            self.log.warning(
                "invalid state change, from %s to %s"
                % (self.skill_control.state, new_state)
            )
            return

        if new_state != self.skill_control.state:

            for intent in self.skill_control.states[self.skill_control.state]:
                self.disable_intent(intent)

            self.skill_control.state = new_state

            for intent in self.skill_control.states[self.skill_control.state]:
                self.enable_intent(intent)

            if new_state == "inactive":
                self.log.debug("send msg: deactivate %s" % (self.skill_id,))
                self.bus.emit(
                    Message("deactivate_skill_request", {"skill_id": self.skill_id})
                )

            if new_state == "active":
                self.log.debug("send msg: activate %s" % (self.skill_id,))
                self.bus.emit(
                    Message(
                        "active_skill_request",
                        {
                            "skill_id": self.skill_id,
                            "skill_cat": self.skill_control.category,
                        },
                    )
                )

    def _register_system_event_handlers(self):
        """Add all events allowing the standard interaction with the Mycroft
        system.
        """
        super()._register_system_event_handlers()

        self.add_event('mycroft.skill.stop', self.__handle_dinkum_stop)
        self.add_event("mycroft.skill-response", self.__handle_dinkum_skill_response)
        self.add_event("mycroft.gui.handle-idle", self.__handle_dinkum_gui_idle)
        self.add_event("mycroft.skills.initialized", self.handle_skills_initialized)

    def handle_skills_initialized(self, message):
        self.skill_service_initializing = False

    def __handle_dinkum_stop(self, message: Message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.log.debug("Handling stop in skill: %s", self.skill_id)
            self._mycroft_session_id = message.data.get("mycroft_session_id")

            result_message: Optional[Message] = None
            try:
                result_message = self.stop()
            except Exception:
                self.log.exception("Error handling stop")

            if result_message is None:
                result_message = self.end_session()

            self.bus.emit(result_message)

    def stop(self) -> Optional[Message]:
        """Optional method implemented by subclass."""
        return self.end_session(gui_clear=GuiClear.AT_END)

    def play_sound_uri(self, uri: str):
        try:  # ovos-core only
            from mycroft.version import OVOS_VERSION_STR
            self.bus.emit(Message("mycroft.audio.queue", data={"filename": uri}))
        except ImportError:  # vanilla mycroft-core
            play_audio(uri).wait()
            return

    def update_gui_values(
            self, page: str, data: Dict[str, Any], overwrite: bool = True
    ):
        # NOTE: dinkum forces a namespace per page, we use regular gui here
        for k, v in data.items():
            self.gui[k] = v

    def _build_actions(
            self,
            dialog: Optional[SessionDialogsType] = None,
            speak: Optional[str] = None,
            speak_wait: bool = True,
            gui: Optional[SessionGuisType] = None,
            gui_clear: GuiClear = GuiClear.AUTO,
            audio_alert: Optional[str] = None,
            music_uri: Optional[str] = None,
            message: Optional[Message] = None,
            message_send: MessageSend = MessageSend.AT_START,
            message_delay: float = 0.0,
            expect_response: bool = False,
    ):
        # Action ordering is fixed:
        # 1. Send message (if "at_start")
        # 2. Clear gui (if "at_start")
        # 3. Play audio alert
        # 4. Show gui page(s)
        # 5. Speak dialog(s) or text
        # 6. Clear gui or set idle timeout
        actions = []

        if expect_response and (gui_clear == GuiClear.AUTO):
            # Don't clear GUI if a response is needed from the user
            gui_clear = GuiClear.NEVER

        # 1. Send message
        if (message is not None) and (message_send == MessageSend.AT_START):
            actions.append(
                {
                    "type": "message",
                    "message_type": message.msg_type,
                    "data": {
                        # Automatically add session id
                        "mycroft_session_id": self._mycroft_session_id,
                        **message.data,
                    },
                }
            )

        # 2. Clear gui (if "at_start")
        if gui_clear == GuiClear.AT_START:
            actions.append({"type": "clear_display"})

        # 3. Play audio alert
        if audio_alert:
            actions.append({"type": "audio_alert", "uri": audio_alert, "wait": True})

        # 4. Show gui page(s)
        guis = []
        if gui is not None:
            if isinstance(gui, (str, tuple)):
                # Single gui
                guis = [gui]
            else:
                guis = list(gui)

        # 5. Speak dialog(s) or text
        dialogs = []
        if dialog is not None:
            if isinstance(dialog, (str, tuple)):
                # Single dialog
                dialogs = [dialog]
            else:
                dialogs = list(dialog)

        # Interleave dialog/gui pages
        for maybe_dialog, maybe_gui in itertools.zip_longest(dialogs, guis):
            if maybe_gui is not None:
                if isinstance(maybe_gui, str):
                    gui_page, gui_data = maybe_gui, None
                else:
                    gui_page, gui_data = maybe_gui

                actions.append(
                    {
                        "type": "show_page",
                        "page": "file://" + self.find_resource(gui_page, "ui"),
                        "data": gui_data,
                        "namespace": f"{self.skill_id}.{gui_page}",
                    }
                )

            if maybe_dialog is not None:
                if isinstance(maybe_dialog, str):
                    dialog_name, dialog_data = maybe_dialog, {}
                else:
                    dialog_name, dialog_data = maybe_dialog

                utterance = self.dialog_renderer.render(dialog_name, dialog_data)
                actions.append(
                    {
                        "type": "speak",
                        "utterance": utterance,
                        "dialog": dialog_name,
                        "dialog_data": dialog_data,
                        "wait": speak_wait,
                    }
                )

        if speak is not None:
            actions.append(
                {
                    "type": "speak",
                    "utterance": speak,
                    "wait": speak_wait,
                }
            )

        if (message is not None) and (message_send == MessageSend.AT_END):
            actions.append(
                {
                    "type": "message",
                    "message_type": message.msg_type,
                    "delay": message_delay,
                    "data": {
                        # Automatically add session id
                        "mycroft_session_id": self._mycroft_session_id,
                        **message.data,
                    },
                }
            )

        if music_uri:
            actions.append({"type": "stream_music", "uri": music_uri})

        if expect_response:
            actions.append({"type": "get_response"})

        if gui_clear == GuiClear.AUTO:
            if guis:
                if dialogs or (speak is not None):
                    # TTS, wait for speak
                    gui_clear = GuiClear.AT_END
                else:
                    # No TTS, so time out on idle
                    gui_clear = GuiClear.ON_IDLE
            else:
                # No GUI, don't clear
                gui_clear = GuiClear.NEVER

        if gui_clear == GuiClear.AT_END:
            actions.append({"type": "clear_display"})
        elif gui_clear == GuiClear.ON_IDLE:
            actions.append({"type": "wait_for_idle"})

        self._exec_actions(actions)  # all compat magic happens here
        return actions

    def _exec_actions(self, actions):
        """ main method for dinkum compat, converts what would be a dinkum session into concrete steps to be executed
        It undoes "dinkum sessions" into standard intent actions executed by skills directly
        """
        for action in actions:
            if action["type"] == "message":
                if action.get("delay"):
                    time.sleep(int(action["delay"]))
                self.bus.emit(Message(action["message_type"], action["data"]))
            elif action["type"] == "clear_display":
                self.gui.clear()
            elif action["type"] == "audio_alert":
                self.play_sound_uri(action["uri"])
            elif action["type"] == "show_page":
                for k, v in action["data"].items():
                    self.gui[k] = v
                self.gui.show_page(action["page"])
            elif action["type"] == "speak" and "dialog" in action:
                self.speak_dialog(action["dialog"], action["dialog_data"], wait=action["wait"])
            elif action["type"] == "speak":
                self.speak(action["utterance"], wait=action["wait"])
            elif action["type"] == "get_response":
                response = self.get_response()
                data = {
                    "mycroft_session_id": self._mycroft_session_id,
                    "skill_id": self.skill_id,
                    "utterances": [response],
                    "state": self.skill_control.state,
                }
                self.bus.emit(Message("mycroft.skill-response", data))
            elif action["type"] == "stream_music":
                self.bus.emit(Message('mycroft.audio.service.play',
                                      {"tracks": [action["uri"]]}))
            elif action["type"] == "wait_for_idle":
                # TODO - bus event
                time.sleep(15)

    def emit_start_session(
            self,
            dialog: Optional[SessionDialogsType] = None,
            speak: Optional[str] = None,
            speak_wait: bool = True,
            gui: Optional[SessionGuisType] = None,
            gui_clear: GuiClear = GuiClear.AUTO,
            audio_alert: Optional[str] = None,
            music_uri: Optional[str] = None,
            expect_response: bool = False,
            message: Optional[Message] = None,
            continue_session: bool = False,
            message_send: MessageSend = MessageSend.AT_START,
            message_delay: float = 0.0,
            mycroft_session_id: Optional[str] = None,
    ) -> str:
        """
        convert session actions into concrete code to be executed

        emit whatever dinkum expects for anything monitoring the bus
        NOTE: a dinkum skills service MUST NOT BE RUNNING or this will have side effects
        the aim is compat with 3rd party apps, not dinkum itself
        """
        if mycroft_session_id is None:
            mycroft_session_id = str(uuid4())

        message = Message(
            "mycroft.session.start",
            data={
                "mycroft_session_id": mycroft_session_id,
                "skill_id": self.skill_id,
                "actions": self._build_actions(
                    dialog=dialog,
                    speak=speak,
                    speak_wait=speak_wait,
                    gui=gui,
                    gui_clear=gui_clear,
                    audio_alert=audio_alert,
                    music_uri=music_uri,
                    message=message,
                    message_send=message_send,
                    message_delay=message_delay,
                    expect_response=expect_response,
                ),
                "continue_session": continue_session,
            },
        )
        self.bus.emit(message)

        return mycroft_session_id

    def continue_session(
            self,
            dialog: Optional[SessionDialogsType] = None,
            speak: Optional[str] = None,
            speak_wait: bool = True,
            gui: Optional[SessionGuisType] = None,
            gui_clear: GuiClear = GuiClear.AUTO,
            audio_alert: Optional[str] = None,
            music_uri: Optional[str] = None,
            expect_response: bool = False,
            message: Optional[Message] = None,
            message_send: MessageSend = MessageSend.AT_START,
            message_delay: float = 0.0,
            mycroft_session_id: Optional[str] = None,
            state: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """
        convert session actions into concrete code to be executed

        emit whatever dinkum expects for anything monitoring the bus
        NOTE: a dinkum skills service MUST NOT BE RUNNING or this will have side effects
        the aim is compat with 3rd party apps, not dinkum itself
        """
        if mycroft_session_id is None:
            # Use session from latest intent handler
            mycroft_session_id = self._mycroft_session_id

        return Message(
            "mycroft.session.continue",
            data={
                "mycroft_session_id": mycroft_session_id,
                "skill_id": self.skill_id,
                "actions": self._build_actions(
                    dialog=dialog,
                    speak=speak,
                    speak_wait=speak_wait,
                    gui=gui,
                    gui_clear=gui_clear,
                    audio_alert=audio_alert,
                    music_uri=music_uri,
                    message=message,
                    message_send=message_send,
                    message_delay=message_delay,
                    expect_response=expect_response,
                ),
                "state": state,
            },
        )

    def end_session(
            self,
            dialog: Optional[SessionDialogsType] = None,
            speak: Optional[str] = None,
            speak_wait: bool = True,
            gui: Optional[SessionGuisType] = None,
            gui_clear: GuiClear = GuiClear.AUTO,
            audio_alert: Optional[str] = None,
            music_uri: Optional[str] = None,
            message: Optional[Message] = None,
            message_send: MessageSend = MessageSend.AT_START,
            message_delay: float = 0.0,
            mycroft_session_id: Optional[str] = None,
    ) -> Message:
        """
        convert session actions into concrete code to be executed

        emit whatever dinkum expects for anything monitoring the bus
        NOTE: a dinkum skills service MUST NOT BE RUNNING or this will have side effects
        the aim is compat with 3rd party apps, not dinkum itself
        """
        if mycroft_session_id is None:
            # Use session from latest intent handler
            mycroft_session_id = self._mycroft_session_id

        return Message(
            "mycroft.session.end",
            data={
                "mycroft_session_id": mycroft_session_id,
                "skill_id": self.skill_id,
                "actions": self._build_actions(
                    dialog=dialog,
                    speak=speak,
                    speak_wait=speak_wait,
                    gui=gui,
                    gui_clear=gui_clear,
                    audio_alert=audio_alert,
                    music_uri=music_uri,
                    message=message,
                    message_send=message_send,
                    message_delay=message_delay,
                ),
            },
        )

    def abort_session(self) -> Message:
        message = self.end_session()
        message.data["aborted"] = True
        return message

    def raw_utterance(
            self, utterance: Optional[str], state: Optional[Dict[str, Any]] = None
    ) -> Optional[Message]:
        """Callback when expect_response=True in continue_session"""
        return None

    def __handle_dinkum_skill_response(self, message: Message):
        """Verifies that raw utterance is for this skill"""
        if (message.data.get("skill_id") == self.skill_id) and (
                message.data.get("mycroft_session_id") == self._mycroft_session_id
        ):
            utterances = message.data.get("utterances", [])
            utterance = utterances[0] if utterances else None
            state = message.data.get("state")
            result_message: Optional[Message] = None
            try:
                self.acknowledge()
                result_message = self.raw_utterance(utterance, state)
            except Exception:
                LOG.exception("Unexpected error in raw_utterance")

            if result_message is None:
                result_message = self.end_session()

            self.bus.emit(result_message)

    def handle_gui_idle(self) -> bool:
        """Allow skill to override idle GUI screen"""
        return False

    def __handle_dinkum_gui_idle(self, message: Message):
        if message.data.get("skill_id") == self.skill_id:
            handled = False
            try:
                handled = self.handle_gui_idle()
            except Exception:
                LOG.exception("Unexpected error handling GUI idle message")
            finally:
                self.bus.emit(message.response(data={"handled": handled}))
