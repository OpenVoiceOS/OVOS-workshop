from ovos_workshop.frameworks.playback.status import *
from ovos_utils.json_helper import merge_dict

class MediaEntry:
    def __init__(self, title, uri, skill_id="ovos.common_play",
                 image=None, match_confidence=0,
                 playback=CommonPlayPlaybackType.UNDEFINED,
                 status = CommonPlayStatus.DISAMBIGUATION, phrase=None,
                 position=0, length=None, bg_image=None, skill_icon=None,
                 **kwargs):
        self.match_confidence = match_confidence
        self.title = title
        self.uri = uri
        self.skill_id = skill_id
        self.status = status
        self.playback = playback
        self.image=image
        self.position = position
        self.phrase = phrase
        self.length = length  # None -> live stream
        self.skill_icon = skill_icon  # TODO default icon
        self.bg_image = bg_image or "https://source.unsplash.com/weekly?music"
        self.data = kwargs

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
        data["status"]= data.get("status") or CommonPlayStatus.DISAMBIGUATION
        data["uri"] = data.get("stream") or data.get("uri") or data.get("url")
        return MediaEntry(**data)

    @property
    def info(self):
        # search results / playlist QML data model
        return merge_dict(self.as_dict, {
            "duration": self.length,
            "track": self.title,
            "image": self.image,
            "album": self.skill_id,
            "source": self.skill_icon
        })

    @property
    def as_dict(self):
        return {k:v for k, v in self.__dict__.items()
                if not k.startswith("_")}

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

    @property
    def entries(self):
        entries = []
        for e in self:
            if isinstance(e, dict):
                e = MediaEntry.from_dict(e)
            if isinstance(e, MediaEntry):
                entries.append(e)
        return entries

    def add_entry(self, entry, index=-1):
        assert isinstance(index, int)
        if isinstance(entry, dict):
            entry = MediaEntry.from_dict(entry)
        assert isinstance(entry, MediaEntry)
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
