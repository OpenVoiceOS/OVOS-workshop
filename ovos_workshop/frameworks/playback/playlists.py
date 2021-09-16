from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG
from ovos_workshop.frameworks.playback.status import *
from ovos_workshop.frameworks.playback.stream_handlers import is_youtube, \
    get_youtube_audio_stream, get_youtube_video_stream, \
    get_deezer_audio_stream, get_rss_first_stream, \
    get_youtube_live_from_channel, find_mime


# TODO subclass from dict (?)
class MediaEntry:
    def __init__(self, title="", uri="", skill_id="ovos.common_play",
                 image=None, match_confidence=0,
                 playback=PlaybackType.UNDEFINED,
                 status=TrackState.DISAMBIGUATION, phrase=None,
                 position=0, length=None, bg_image=None, skill_icon=None,
                 artist=None,
                 **kwargs):
        self.match_confidence = match_confidence
        self.title = title
        self.uri = uri
        self.artist = artist
        self.skill_id = skill_id
        self.status = status
        self.playback = playback
        self.image = image
        self.position = position
        self.phrase = phrase
        self.length = length  # None -> live stream
        self.skill_icon = skill_icon  # TODO default icon
        self.bg_image = bg_image or "https://source.unsplash.com/weekly?music"
        self.data = kwargs

    def update(self, entry, skipkeys=None):
        skipkeys = skipkeys or []
        if isinstance(entry, MediaEntry):
            entry = entry.as_dict
        for k, v in entry.items():
            if k not in skipkeys and hasattr(self, k):
                self.__setattr__(k, v)

    @staticmethod
    def from_dict(data):
        if data.get("bg_image", "").startswith("/"):
            data["bg_image"] = "file:/" + data["bg_image"]
        data["skill"] = data.get("skill_id", "ovos.common_play")
        data["position"] = data.get("position", 0)
        data["length"] = data.get("length") or \
                         data.get("track_length") or \
                         data.get("duration")  # or get_duration_from_url(url)
        data["skill_icon"] = data.get("skill_icon") or data.get("skill_logo")
        data["status"] = data.get("status") or TrackState.DISAMBIGUATION
        data["uri"] = data.get("stream") or data.get("uri") or data.get("url")
        data["title"] = data.get("title") or data["uri"]
        data["artist"] = data.get("artist") or data.get("author")
        return MediaEntry(**data)

    @property
    def info(self):
        # media results / playlist QML data model
        return merge_dict(self.as_dict, {
            "duration": self.length,
            "track": self.title,
            "image": self.image,
            "album": self.skill_id,
            "source": self.skill_icon
        })

    @property
    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()
                if not k.startswith("_")}

    @property
    def mimetype(self):
        if self.uri:
            return find_mime(self.uri)

    def extract_stream(self):
        uri = self.uri
        if self.playback == PlaybackType.VIDEO:
            video = True
        else:
            video = False
        meta = {}
        if uri.startswith("rss//"):
            uri = uri.replace("rss//", "")
            meta = get_rss_first_stream(uri)
            if not meta:
                LOG.error("RSS feed stream extraction failed!!!")

        if uri.startswith("deezer//"):
            uri = uri.replace("deezer//", "")
            meta = get_deezer_audio_stream(uri)
            if not meta:
                LOG.error("deezer stream extraction failed!!!")
            else:
                LOG.debug(f"deezer cache: {meta['uri']}")

        if uri.startswith("youtube.channel.live//"):
            uri = uri.replace("youtube.channel.live//", "")
            uri = get_youtube_live_from_channel(uri)
            if not uri:
                LOG.error("youtube channel live stream extraction failed!!!")
            else:
                uri = "youtube//" + uri

        if uri.startswith("youtube//") or is_youtube(uri):
            uri = uri.replace("youtube//", "")
            if not video:
                meta = get_youtube_audio_stream(uri)
            if video or not meta:
                meta = get_youtube_video_stream(uri)
            if not meta:
                LOG.error("youtube stream extraction failed!!!")
        meta = meta or {"uri": uri}

        # update media entry with new data
        self.update(meta)

    def __eq__(self, other):
        if isinstance(other, MediaEntry):
            other = other.as_dict
        # dict compatison
        return other == self.as_dict

    def __repr__(self):
        return str(self.as_dict)

    def __str__(self):
        return str(self.as_dict)


class Playlist(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.position = 0

    @property
    def entries(self):
        entries = []
        for e in self:
            if isinstance(e, dict):
                e = MediaEntry.from_dict(e)
            if isinstance(e, MediaEntry):
                entries.append(e)
        return entries

    def sort_by_conf(self):
        self.sort(
            key=lambda k: k.match_confidence
            if isinstance(k, MediaEntry) else k.get("match_confidence", 0),
            reverse=True)

    def add_entry(self, entry, index=-1):
        assert isinstance(index, int)
        if isinstance(entry, dict):
            entry = MediaEntry.from_dict(entry)
        assert isinstance(entry, MediaEntry)
        if index == -1:
            index = len(self)
        self.insert(index, entry)

    def remove_entry(self, entry):
        if isinstance(entry, int):
            self.pop(entry)
            return
        if isinstance(entry, dict):
            entry = MediaEntry.from_dict(entry)
        assert isinstance(entry, MediaEntry)
        for idx, e in self.entries:
            if e == entry:
                self.pop(idx)
                break
        else:
            raise ValueError("entry not in playlist")

    def __contains__(self, item):
        if isinstance(item, dict):
            item = MediaEntry.from_dict(item)
        if not isinstance(item, MediaEntry):
            return False
        for e in self.entries:
            if e == item:
                return True
        return False

    @property
    def current_track(self):
        if len(self) == 0:
            return None
        if self.position >= len(self):
            LOG.error("Playlist pointer is in an invalid position! Going to "
                      "start of playlist")
            self.position = 0
        return self[self.position]

    def next_track(self):
        self.position += 1
        if self.position >= len(self):
            self.position = 0

    def prev_track(self):
        self.position -= 1
        self.position = max(0, self.position)

