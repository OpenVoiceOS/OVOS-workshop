import random
from os.path import join, dirname, basename

from json_database import JsonStorageXDG
from ovos_plugin_common_play.ocp import MediaType, PlaybackType
from ovos_utils import datestr2ts, resolve_ovos_resource_file
from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG
from ovos_utils.messagebus import Message
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill

try:
    import pyvod
except ImportError:
    LOG.error("py_VOD not installed!")
    LOG.debug("py_VOD>=0.4.0")
    pyvod = None


class VideoCollectionSkill(OVOSCommonPlaybackSkill):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "max_videos" not in self.settings:
            self.settings["max_videos"] = 500
        if "min_duration" not in self.settings:
            self.settings["min_duration"] = -1
        if "max_duration" not in self.settings:
            self.settings["max_duration"] = -1
        if "shuffle_menu" not in self.settings:
            self.settings["shuffle_menu"] = False
        if "filter_live" not in self.settings:
            self.settings["filter_live"] = False
        if "filter_date" not in self.settings:
            self.settings["filter_date"] = False
        if "min_score" not in self.settings:
            self.settings["min_score"] = 40
        if "match_description" not in self.settings:
            self.settings["match_description"] = True
        if "match_tags" not in self.settings:
            self.settings["match_tags"] = True
        if "match_title" not in self.settings:
            self.settings["match_title"] = True
        if "filter_trailers" not in self.settings:
            self.settings["filter_trailers"] = True
        if "filter_behind_scenes" not in self.settings:
            self.settings["filter_behind_scenes"] = True

        if pyvod is None:
            LOG.error("py_VOD not installed!")
            LOG.info("pip install py_VOD>=0.4.0")
            raise ImportError
        self.playback_type = PlaybackType.VIDEO
        self.media_type = MediaType.VIDEO
        self.default_bg = "https://github.com/OpenVoiceOS/ovos_assets/raw/master/Logo/ovos-logo-512.png"
        self.default_image = resolve_ovos_resource_file(
            "ui/images/moviesandfilms.png")
        db_path = join(dirname(__file__), "res", self.name + ".jsondb")
        self.message_namespace = basename(dirname(__file__)) + ".ovos_utils"
        self.media_collection = pyvod.Collection(self.name,
                                                 logo=self.default_image,
                                                 db_path=db_path)
        self.skill_icon = self.skill_logo = self.default_image

    def initialize(self):
        self.initialize_media_commons()

    def initialize_media_commons(self):
        # generic ovos events
        self.gui.register_handler("ovos.common_play.collection.play",
                                  self.play_video_event)
        self.gui.register_handler("ovos.common_play.collection.clear_history",
                                  self.handle_clear_history)

        # skill specific events
        self.add_event(
            '{msg_base}.home'.format(msg_base=self.message_namespace),
            self.handle_homescreen)
        self.gui.register_handler(
            "{msg_base}.play_event".format(msg_base=self.message_namespace),
            self.play_video_event)
        self.gui.register_handler(
            "{msg_base}.clear_history".format(msg_base=self.message_namespace),
            self.handle_clear_history)

    @property
    def videos(self):
        try:
            # load video catalog
            videos = [ch.as_json() for ch in self.media_collection.entries]
            # set skill_id
            for idx, v in enumerate(videos):
                videos[idx]["skill"] = self.skill_id
                # set url
                if len(videos[idx].get("streams", [])):
                    videos[idx]["url"] = videos[idx]["streams"][0]
                else:
                    videos[idx]["url"] = videos[idx].get("stream") or \
                                         videos[idx].get("url")
                # convert duration to milliseconds
                if v.get("duration"):
                    videos[idx]["length"] = v["duration"] * 1000
            # return sorted
            return self.sort_videos(videos)
        except Exception as e:
            LOG.exception(e)
            return []

    # homescreen / menu
    def sort_videos(self, videos):
        # sort by upload date
        if self.settings["filter_date"]:
            videos = sorted(videos,
                            key=lambda kv: datestr2ts(kv.get("upload_date")),
                            reverse=True)

        # this will filter live videos
        live = [v for v in videos if v.get("is_live")]
        videos = [v for v in videos if not v.get("is_live")]

        # live streams before videos
        return live + videos

    def filter_videos(self, videos):
        # this will filter private videos in youtube
        if self.settings["filter_date"]:
            videos = [v for v in videos if v.get("upload_date")]

        # this will filter live videos
        live = [v for v in videos if v.get("is_live")]
        videos = [v for v in videos if not v.get("is_live")]

        # filter by duration
        if self.settings["min_duration"] > 0 or \
                self.settings["max_duration"] > 0:
            videos = [v for v in videos if
                      v.get("duration")]  # might be missing

        if self.settings["min_duration"] > 0:
            videos = [v for v in videos if int(v.get("duration", 0)) >=
                      self.settings["min_duration"]]
        if self.settings["max_duration"] > 0:
            videos = [v for v in videos if int(v.get("duration", 0)) <=
                      self.settings["max_duration"]]

        # TODO filter behind the scenes, clips etc based on
        #  title/tags/description/keywords required or forbidden

        # filter trailers
        if self.settings["filter_trailers"] and \
                MediaType.TRAILER not in self.supported_media:
            # TODO bundle .voc for "trailer"
            videos = [v for v in videos
                      if not self.voc_match(v["title"], "trailer")]

        # filter behind the scenes
        if self.settings["filter_behind_scenes"] and \
                MediaType.BEHIND_THE_SCENES not in self.supported_media:
            # TODO bundle .voc for "behind_scenes"
            videos = [v for v in videos
                      if not self.voc_match(v["title"], "behind_scenes")]

        if self.settings["shuffle_menu"]:
            random.shuffle(videos)

        if self.settings["max_videos"]:
            # rendering takes forever if there are too many entries
            videos = videos[:self.settings["max_videos"]]

        # this will filter live videos
        if self.settings["filter_live"]:
            return videos
        return live + videos

    def handle_homescreen(self, message):
        self.gui.clear()
        self.gui["videosHomeModel"] = self.filter_videos(self.videos)
        self.gui["historyModel"] = JsonStorageXDG(
            "{msg_base}.history".format(msg_base=self.message_namespace)) \
            .get("model", [])
        self.gui.show_page("SYSTEM_MediaCollectionSkillHomescreen.qml",
                           override_idle=True)

    def play_video_event(self, message):
        video_data = message.data["modelData"]
        if video_data["skill_id"] == self.skill_id:
            # ensure all data fields present
            video_data = merge_dict(video_data, {
                "match_confidence": 100,
                "media_type": self.media_type,
                "playback": self.playback_type,
                "skill_icon": self.skill_icon,
                "skill_logo": self.skill_logo,
                "bg_image": video_data.get("logo") or self.default_bg,
                "image": video_data.get("logo") or self.default_image,
                "author": self.name
            })
            self.bus.emit(Message("ovos.common_play.collection.play", {
                "playlistData": [video_data],
                "collection": self.videos[:50]
            }))

    # watch history database
    def add_to_history(self, video_data):
        # History
        historyDB = JsonStorageXDG(
            "{msg_base}.history".format(msg_base=self.message_namespace))
        if "model" not in historyDB:
            historyDB["model"] = []
        historyDB["model"].append(video_data)
        historyDB.store()
        self.gui["historyModel"] = historyDB["model"]

    def handle_clear_history(self, message):
        video_data = message.data["modelData"]
        if video_data["skill_id"] == self.skill_id:
            historyDB = JsonStorageXDG("{msg_base}.history"
                                       .format(
                msg_base=self.message_namespace))
            historyDB["model"] = []
            historyDB.store()
