import time

from ovos_utils.gui import is_gui_connected, is_gui_running
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message
from ovos_workshop.frameworks.playback.mycroft_cps import \
    MycroftCommonPlayInterface
from ovos_workshop.frameworks.playback.settings import CommonPlaySettings
from ovos_workshop.frameworks.playback.status import *
from ovos_workshop.frameworks.playback.playlists import Playlist


class OVOSMediaSearch:
    def __init__(self, player):
        """
        player: OVOSCommonPlaybackInterface
        """
        self._player = player
        self.search_playlist = Playlist()
        self.active_skills = []
        self.query_replies = {}
        self.query_timeouts = {}
        self.searching = False
        self.search_start = 0
        self.old_cps = MycroftCommonPlayInterface(self.bus) if \
            self.settings.backwards_compatibility else None
        self.register_bus_handlers()

    def register_bus_handlers(self):
        self.bus.on("ovos.common_play.skill.search_start",
                    self.handle_skill_search_start)
        self.bus.on("ovos.common_play.skill.search_end",
                    self.handle_skill_search_end)
        self.bus.on("ovos.common_play.query.response",
                    self.handle_skill_response)

    def shutdown(self):
        self.bus.remove("ovos.common_play.skill.search_start",
                        self.handle_skill_search_start)
        self.bus.remove("ovos.common_play.skill.search_end",
                        self.handle_skill_search_end)
        self.bus.remove("ovos.common_play.query.response",
                        self.handle_skill_response)

    @property
    def settings(self):
        return self._player.settings

    @property
    def gui(self):
        return self._player.gui

    @property
    def bus(self):
        return self._player.bus

    def handle_skill_search_start(self, message):
        skill_id = message.data["skill_id"]
        LOG.debug(f"{message.data['skill_id']} is searching")
        if skill_id not in self.active_skills:
            self.active_skills.append(skill_id)

    def handle_skill_response(self, message):
        search_phrase = message.data["phrase"]
        timeout = message.data.get("timeout")
        skill_id = message.data['skill_id']
        # LOG.debug(f"OVOSCommonPlay result: {skill_id}")

        if message.data.get("searching"):
            # extend the timeout by N seconds
            if timeout and self.settings.allow_extensions and \
                    search_phrase in self.query_timeouts:
                self.query_timeouts[search_phrase] += timeout
            # else -> expired media

        elif search_phrase in self.query_replies:
            # Collect replies until the timeout
            if not self.searching and not len(self.query_replies[search_phrase]):
                LOG.debug("  too late!! ignored in track selection process")
                LOG.warning(
                    f"{message.data['skill_id']} is not answering fast "
                    "enough!")

            has_gui = is_gui_running() or is_gui_connected(self.bus)
            for idx, res in enumerate(message.data.get("results", [])):
                # filter video results if GUI not connected
                if not has_gui:
                    # force allowed stream types to be played audio only
                    if res.get("media_type", "") in \
                            CommonPlaySettings.cast2audio:
                        LOG.debug("unable to use GUI, forcing result to play audio only")
                        res["playback"] = PlaybackType.AUDIO
                        res["match_confidence"] -= 10
                        message.data["results"][idx] = res

                if res not in self.search_playlist:
                    self.search_playlist.add_entry(res)
                    # update media UI
                    if self.searching and res["match_confidence"] >= 30:
                        self.gui["footer_text"] = \
                            f"skill - {skill_id}\n" \
                            f"match - {res['title']}\n" \
                            f"confidence - {res['match_confidence']} "

            self.query_replies[search_phrase].append(message.data)

            # abort searching if we gathered enough results
            # TODO ensure we have a decent confidence match, if all matches
            #  are < 50% conf extend timeout instead
            if time.time() - self.search_start > self.query_timeouts[
                search_phrase]:
                if self.searching:
                    self.searching = False
                    LOG.debug("common play query timeout, parsing results")
                    self.gui["footer_text"] = "Timeout!\n " \
                                              "selecting best result\n" \
                                              " "

        elif self.searching:
            for res in message.data.get("results", []):
                if res.get("match_confidence",
                           0) >= self.settings.early_stop_thresh:
                    # got a really good match, dont media further
                    LOG.info("Receiving very high confidence match, stopping "
                             "media early")
                    self.gui["footer_text"] = \
                        f"High confidence match!\n "\
                            f"skill - {skill_id}\n" \
                            f"match - {res['title']}\n" \
                            f"confidence - {res['match_confidence']} "
                    # allow other skills to "just miss"
                    if self.settings.early_stop_grace_period:
                        LOG.debug(
                            f"  - grace period: {self.settings.early_stop_grace_period} seconds")
                        time.sleep(self.settings.early_stop_grace_period)
                    self.searching = False
                    return

    def handle_skill_search_end(self, message):
        skill_id = message.data["skill_id"]
        LOG.debug(f"{message.data['skill_id']} finished media")
        if skill_id in self.active_skills:
            self.active_skills.remove(skill_id)

        # if this was the last skill end searching period
        time.sleep(0.5)
        # TODO this sleep is hacky, but avoids a race condition in
        # case some skill just decides to respond before the others even
        # acknowledge media is starting, this gives more than enough time
        # for self.active_seaching to be populated, a better approach should
        # be employed but this works fine for now
        if not self.active_skills and self.searching:
            LOG.info("Received media responses from all skills!")
            self.gui["footer_text"] = "Received media responses from all skills!\n" \
                                      "selecting best result"
            self.searching = False
        self.gui.update_search_results()

    def search(self, phrase, media_type=MediaType.GENERIC):
        self.gui.show_search_spinner()
        self.clear()
        self.query_replies[phrase] = []
        self.query_timeouts[phrase] = self.settings.min_timeout
        self.search_start = time.time()
        self.searching = True
        self.bus.emit(Message('ovos.common_play.query',
                              {"phrase": phrase,
                               "question_type": media_type}))
        # old common play will send the messages expected by the official
        # mycroft stack, but skills are know to over match, dont support
        # match type, and the VIDEO is different for every skill, it may also
        # cause issues with status tracking and mess up playlists
        if self.old_cps:
            self.old_cps.send_query(phrase, media_type)

        # if there is no match type defined, lets increase timeout a bit
        # since all skills need to media
        if media_type == MediaType.GENERIC:
            bonus = 3  # timeout bonus
        else:
            bonus = 0

        while self.searching and \
                time.time() - self.search_start <= self.settings.max_timeout + bonus:
            time.sleep(0.1)

        self.searching = False

        # convert the returned data to the expected new format, playback
        # type is consider Skill, ovos common play will not handle the playback
        # life cycle but instead delegate to the skill
        if self.old_cps:
            old_style = self.old_cps.get_results(phrase)
            self.query_replies[phrase] += self._mycroft2ovos(old_style,
                                                             media_type)
        self.gui.update_search_results()
        if self.query_replies.get(phrase):
            return [s for s in self.query_replies[phrase] if s.get("results")]

        # fallback to generic media type
        if self.settings.media_fallback and media_type != MediaType.GENERIC:
            # TODO dont query skills that found results for non-generic
            #  query again
            LOG.debug(
                "OVOSCommonPlay falling back to MediaType.GENERIC")
            return self.search(phrase, media_type=MediaType.GENERIC)
        return []

    def search_skill(self, skill_id, phrase,
                     media_type=MediaType.GENERIC):
        res = [r for r in self.search(phrase, media_type)
               if r["skill_id"] == skill_id]
        if not len(res):
            return None
        return res[0]

    def clear(self):
        self.search_playlist = Playlist()
        self.gui.update_search_results()

    # TODO move to mycroft class
    @staticmethod
    def _mycroft2ovos(results, media_type=MediaType.GENERIC):
        new_style = []
        for res in results:
            data = res['callback_data']
            data["skill_id"] = res["skill_id"]
            data["phrase"] = res["phrase"]
            data["is_old_style"] = True  # internal flag for playback handling
            data['match_confidence'] = res["conf"] * 100
            data["uri"] = data.get("stream") or \
                          data.get("url") or \
                          data.get("uri")

            # Essentially a random guess....
            data["question_type"] = media_type
            data["playback"] = PlaybackType.SKILL
            if not data.get("image"):
                data["image"] = data.get("logo") or \
                                data.get("picture")
            if not data.get("bg_image"):
                data["bg_image"] = data.get("background") or \
                                   data.get("bg_picture") or \
                                   data.get("logo") or \
                                   data.get("picture")

            new_style.append({'phrase': res["phrase"],
                              "is_old_style": True,
                              'results': [data],
                              'searching': False,
                              'skill_id': res["skill_id"]})
        return new_style
