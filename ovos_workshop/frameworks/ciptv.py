import time
from threading import Thread, Event

from ovos_utils.messagebus import get_mycroft_bus, Message
from ovos_utils.json_helper import merge_dict, is_compatible_dict
from ovos_utils.parse import match_all, MatchStrategy, match_one, fuzzy_match
from ovos_utils.log import LOG

from ovos_workshop.utils import check_stream, StreamStatus, M3UParser


class CommonIPTV(Thread):
    stream_providers = {}
    channels = {}
    dead_channels = {}
    remove_threshold = 2  # stream dead N checks in a row is removed
    time_between_updates = 30  # minutes between re-checking stream status of
                               # expired {TTL} channels
    max_checks = 15  # max number of streams to check every {time_between_updates}
    _duplicates = {}  # url:[idx] uniquely identifying duplicate channels
    _duplicate_candidates = {}  # url:[idx] uniquely identifying possible
                                # duplicates (fuzzy tvg-id matching)
    duplicate_threshold = 0.95  # if fuzzy_match confidence is above,
                                # merge channels
    bus = None  # mycroft bus connection

    def __init__(self, bus=None, *args, **kwargs):
        if bus:
            self.bind(bus)
        self.stop_event = Event()
        self._last_check = time.time()
        super(CommonIPTV, self).__init__(*args, **kwargs)

    @classmethod
    def bind(cls, bus=None):
        cls.bus = bus or get_mycroft_bus()

    # low level actions
    @classmethod
    def add_stream_provider(cls, stream_provider):
        if isinstance(stream_provider, str):
            stream_provider = {"url": stream_provider}

        url = stream_provider["url"]
        ttl = stream_provider.get("ttl") or 6 * 60 * 60
        stream_provider["expires"] = time.time() + ttl
        cls.stream_providers[url] = stream_provider
        cls.import_m3u8(url, stream_provider.get("tags"))

    @classmethod
    def delete_stream_provider(cls, stream_provider):
        if isinstance(stream_provider, dict):
            url = stream_provider["url"]
        else:
            url = stream_provider
        if url in cls.stream_providers:
            cls.stream_providers.pop(url)

    @classmethod
    def add_channel(cls, channel):
        url = channel.get("stream")
        channel_id = cls.channel2id(channel)

        if url in [ch.get("stream") for idx, ch in cls.dead_channels.items()]:
            LOG.error("Channel has been previously flagged DEAD, refused to "
                      "add channel")
            LOG.debug(str(channel))
            return

        for idx, ch in cls.channels.items():
            ch_url = ch["stream"]
            if url != ch_url:
                continue
            LOG.debug(f"Stream previously added: {url}")
            if is_compatible_dict(ch, channel):
                LOG.debug(f"merging channel data {channel_id}:{idx}")
                cls.channels[idx] = cls.create_merged_channel(ch, channel)
                return

            else:
                if channel_id in cls.channels:
                    LOG.error(f"channel data doesn't "
                              f"match, {channel_id} already in database")
                LOG.warning("refused to merge, replacing channel")

        LOG.info(f"Adding channel: {channel_id}")
        channel["expires"] = 0
        channel["status"] = StreamStatus.UNKNOWN
        channel["_dead_counter"] = 0
        cls.channels[channel_id] = channel

    @classmethod
    def delete_channel(cls, key):
        if key in cls.channels:
            cls.channels.pop(key)
            return
        for idx, ch in cls.channels.items():
            if ch.get("id") == key:
                cls.channels.pop(key)
                return
            elif ch.get("identifier") == key:
                cls.channels.pop(key)
                return
            elif ch.get("uri") == key:
                cls.channels.pop(key)
                return
            elif ch.get("stream") == key:
                cls.channels.pop(key)
                return
            elif ch.get("url") == key:
                cls.channels.pop(key)
                return
            elif ch.get("title") == key:
                cls.channels.pop(key)
                return

    @classmethod
    def import_m3u8(cls, url, tags=None):
        tags = tags or []

        LOG.info(f"Importing m3u8: {url}")
        tv = M3UParser.parse_m3u8(url)
        for r in tv:
            default_tags = ["TV", "IPTV"]
            if r.get("group-title"):
                default_tags.append(r['group-title'])
            if r.get("stream"):
                entry = {
                    "title": r["title"],
                    "duration": r["duration"],
                    "category": r.get('group-title'),
                    "logo": r.get('tvg-logo'),
                    "stream": r.get("stream"),
                    "identifier": r.get("tvg-id"),
                    "tags": tags + default_tags,
                    "country": r.get("tvg-country"),
                    "lang": r.get("tvg-language")
                }
                if r.get("group-title"):
                    entry["tags"].append(r["group-title"])
                if r.get("tvg-country"):
                    entry["tags"].append(r["tvg-country"])
                if r.get("tvg-language"):
                    entry["tags"].append(r["tvg-language"])
                cls.add_channel(entry)

    @classmethod
    def get_channel_status(cls, channel):
        if isinstance(channel, str):
            channel = cls.find_channel(channel)
        stream = channel.get("stream")
        if not stream:
            if channel.get("stream_callback"):
                data = cls.bus.wait_response(Message(channel["stream_callback"]))
                # callback mode to ask stream provider (skill) for actual url
                # - we have a message type in payload instead of stream
                # - we send that bus message and wait reply with actual stream
                # - allows searching without extracting (slow), eg, youtube
                if data and data.get("stream"):
                    return check_stream(data["stream"], timeout=5)
            raise KeyError("channel has no associated stream")
        return check_stream(stream, timeout=5)

    @classmethod
    def find_channel(cls, key):
        if key in cls.channels:
            return cls.channels[key]
        for idx, ch in cls.channels.items():
            if ch.get("id") == key:
                return ch
            elif ch.get("identifier") == key:
                return ch
            elif ch.get("uri") == key:
                return ch
            elif ch.get("stream") == key:
                return ch
            elif ch.get("url") == key:
                return ch
            elif ch.get("title") == key:
                return ch

    @staticmethod
    def channel2id(channel):
        return channel.get("identifier") or channel.get("id") or \
                     channel.get("tvg-id") or channel.get("title")

    # automated actions
    @classmethod
    def prune_dead_streams(cls, ttl=60):
        """ remove dead streams from channel list
        set stream status as OK for ttl minutes"""
        for idx, ch in dict(cls.channels).items():
            if cls.channels[idx]["status"] != StreamStatus.OK:
                cls.channels[idx]["status"] = cls.get_channel_status(ch)
                cls.channels[idx]["expires"] = time.time() + ttl * 60
                if cls.channels[idx]["status"] == StreamStatus.OK:
                    cls.channels[idx]["_dead_counter"] = 0
                else:
                    cls.channels[idx]["_dead_counter"] += 1
                    if cls.channels[idx]["_dead_counter"] >= \
                            cls.remove_threshold:
                        LOG.info(f"Removing dead stream: {idx}")
                        cls.dead_channels[idx] = ch
                        cls.delete_channel(idx)

    @classmethod
    def update_stream_status(cls, ttl=120):
        # order channels by expiration date
        channels = sorted([(idx, ch)
                           for idx, ch in dict(cls.channels).items()],
                          key=lambda k: k[1]["expires"])
        # update N channels status
        for idx, ch in channels[:cls.max_checks]:
            if cls.channels[idx]["expires"] - time.time() < 0:
                cls.channels[idx]["status"] = cls.get_channel_status(ch)
                cls.channels[idx]["expires"] = time.time() + ttl * 60
                LOG.info(f'{idx} stream status: {cls.channels[idx]["status"]}')

    @classmethod
    def update_streams(cls):
        for url, provider in cls.stream_providers.items():
            if provider["expires"] - time.time() < 0:
                # will add new channels and ignore duplicated/known dead ones
                # NOTE: dead channels are flagged in a different stage
                cls.add_stream_provider(provider)

    @classmethod
    def find_duplicate_streams(cls):
        """ detect streams that are duplicated by several skills """
        for prev_idx, prev_ch in cls.channels.items():
            prev_url = prev_ch.get("stream")
            for idx, ch in dict(cls.channels).items():
                if idx == prev_idx:
                    continue
                url = ch.get("stream")

                if url == prev_url and False:
                    score = 1.0
                else:
                    score = fuzzy_match(ch["title"].lower(),
                                        prev_ch["title"].lower())

                if score >= cls.duplicate_threshold:
                    if idx not in cls._duplicates:
                        LOG.info(f"Duplicate channel: {prev_idx}:{idx} - "
                                 f"confidence: {score}")
                        cls._duplicates[idx] = [prev_idx]
                    elif prev_idx not in cls._duplicates[idx]:
                        cls._duplicates[idx].append(prev_idx)

    @classmethod
    def merge_duplicate_channels(cls):
        for idx, chs in cls._duplicates.items():
            ch = cls.channels.get(idx)
            if not ch:
                continue
            for idx2 in chs:
                if idx2 == idx:
                    continue
                ch2 = cls.channels.get(idx2)
                if not ch2:
                    continue

                merged_ch = cls.create_merged_channel(ch, ch2)
                if merged_ch:
                    LOG.debug(f"merging channel data {idx}:{idx2}")
                    cls.delete_channel(idx)
                    cls.delete_channel(idx2)
                    cls.add_channel(merged_ch)

    @staticmethod
    def create_merged_channel(base, delta, precedence="longest"):
        if is_compatible_dict(base, delta):
            if precedence == "base":
                return merge_dict(base, delta, merge_lists=True,
                                  new_only=True, no_dupes=True, skip_empty=True)
            elif precedence == "delta":
                return merge_dict(base, delta, merge_lists=True,
                                  no_dupes=True, skip_empty=True)
            elif precedence == "longest":
                for key in [k for k in delta if k in base]:
                    if isinstance(base[key], str) and isinstance(delta[key], str):
                        if len(base[key]) > len(delta[key]):
                            delta[key] = base[key]
                if delta.get("skill_id") and base.get("skill_id") \
                        and base.get("skill_id") not in delta.get("skill_id"):
                    delta["skill_id"] = delta["skill_id"] + "/" + base["skill_id"]
                return merge_dict(base, delta, merge_lists=True,
                                  no_dupes=True, skip_empty=True)

        else:
            return None

    # iptv functionality
    def get_channels(self, filter_dead=False):
        if filter_dead:
            return [ch for idx, ch in self.channels.items()
                    if ch["status"] == StreamStatus.OK]
        return [ch for idx, ch in self.channels.items()]

    def search(self, query, lang=None,
               strategy=MatchStrategy.TOKEN_SORT_RATIO, filter_dead=False,
               minconf=50):
        query = query.lower().strip()
        if lang:
            channels = self.filter_by_language(lang)
        else:
            channels = self.get_channels()
        matches = []
        for ch in channels:
            # score name match
            names = ch.get("aliases") or []
            names.append(ch.get("title") or ch["identifier"])
            names = [_.lower().strip() for _ in names]
            best_name, name_score = match_one(query, names, strategy=strategy)
            name_score = name_score * 50
            if query in best_name:
                name_score += 30

            # score tag matches
            tags = ch.get("tags", [])
            tags = [_.lower().strip() for _ in tags]
            tag_scores = match_all(query, tags, strategy=strategy)[:5]
            tag_score = sum([0.5 * t[1] for t in tag_scores]) / len(
                tag_scores) * 100
            if query in tags:
                tag_score += 30

            score = min(tag_score + name_score, 100)
            if score >= minconf:
                if not filter_dead:
                    matches.append((ch, score))
                elif ch["status"] == StreamStatus.OK:
                    matches.append((ch, score))

        return sorted(matches, key=lambda k: k[1], reverse=True)

    def filter_by_language(self, lang):
        return [c for c in self.get_channels() if
                c.get("lang") == lang or
                c.get("lang", "").split("-")[0] == lang or
                lang in c.get("secondary_langs", [])]

    # event loop
    def run(self) -> None:
        self.stop_event.clear()
        while not self.stop_event.is_set():
            # take note of duplicated channels
            self.find_duplicate_streams()
            # merge entries
            self.merge_duplicate_channels()
            # remove any dead streams
            self.prune_dead_streams()
            # verify streams
            if time.time() - self._last_check > self.time_between_updates * 60:
                # update new streams
                self.update_streams()
                # confirm working status of existing streams
                self.update_stream_status()
                self._last_check = time.time()

    def stop(self):
        self.stop_event.set()

    # bus api
    def handle_register_m3u(self, message):
        url = message.data["url"]
        ttl = message.data.get("ttl") or 24 * 60 * 60
        self.add_stream_provider({"url": url, "ttl": ttl})

    def handle_register_channel(self, message):
        self.add_channel(message.data)

    def handle_deregister_m3u(self, message):
        url = message.data["url"]
        self.delete_stream_provider(url)

    def handle_deregister_channel(self, message):
        ch = self.channel2id(message.data)
        self.delete_channel(ch)
