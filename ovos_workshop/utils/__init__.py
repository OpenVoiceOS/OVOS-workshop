from ovos_workshop.utils.youtube import get_youtube_metadata, is_youtube
import requests
from os.path import join
from tempfile import gettempdir
from enum import IntEnum


class StreamStatus(IntEnum):
    OK = 200
    DEAD = 404
    FORBIDDEN = 401
    ERROR = 500
    UNKNOWN = 0


def check_stream(url, timeout=3):
    # verify is url is dead or alive
    try:
        s = requests.get(url, timeout=timeout).status_code
        if s == 200:
            return StreamStatus.OK
        if s == 404:
            return StreamStatus.DEAD
        elif str(s).startswith("4"):
            return StreamStatus.FORBIDDEN
    except Exception as e:
        # error, usually a 500
        return StreamStatus.ERROR
    return StreamStatus.UNKNOWN


class M3UParser:
    @staticmethod
    def parse_extinf(header):
        # remove double spaces
        header = " ".join([w for w in header.split(" ") if w])
        values, name = header.replace("#EXTINF:", "").split(",")
        values = values.split("=")
        _ = values[0].split(" ")
        if len(_) == 1:
            duration = _[0]
        else:
            duration, k = _
        data = {"title": name, "duration": int(duration)}
        for d in values[1:]:
            val = " ".join(d.split(" ")[:-1])
            if val:
                data[k] = val.rstrip('"').lstrip('"')
                k = d.split(" ")[-1]
            else:
                data[k] = d.rstrip('"').lstrip('"')
        data["tvg-id"] = data.get("tvg-id") or name
        return data

    @staticmethod
    def parse_m3u8(m3):
        if m3.startswith("http"):
            content = requests.get(m3).content
            m3 = join(gettempdir(), f"{str(hash(m3))[1:]}_pyvod.m3u8")
            with open(m3, "wb") as f:
                f.write(content)
        with open(m3) as f:
            m3ustr = f.read().split("\n")
            m3ustr = [l for l in m3ustr if l.strip()]

        streamz = []
        m3ustr = [ l for l in m3ustr if
                   l.startswith("#EXTINF:") or l.startswith("http")]
        for idx, line in enumerate(m3ustr):
            next_line = m3ustr[idx + 1] if idx + 1 < len(m3ustr) else None
            if line.startswith("#EXTINF:"):
                data = M3UParser.parse_extinf(line)
                if next_line.startswith("http"):
                    data["stream"] = next_line
                    streamz.append(data)

        return streamz

    @staticmethod
    def get_group_titles(titles, m3):
        if isinstance(titles, str):
            titles = [titles]
        titles = [t.lower().strip() for t in titles]
        entries = M3UParser.parse_m3u8(m3)
        return [v for v in entries
                if v.get("group-title", "").lower().strip() in titles]

    @staticmethod
    def get_tvg_id(tvgs, m3):
        if isinstance(tvgs, str):
            tvgs = [tvgs]
        tvgs = [t.lower().strip() for t in tvgs]
        entries = M3UParser.parse_m3u8(m3)
        return [v for v in entries if
                v.get("tvg-id", "").lower().strip() in tvgs]

    @staticmethod
    def get_titles(titles, m3):
        if isinstance(titles, str):
            titles = [titles]
        titles = [t.lower().strip() for t in titles]
        entries = M3UParser.parse_m3u8(m3)
        return [v for v in entries if v.get("title", "").lower() in titles]

    @staticmethod
    def get_channel(queries, m3):
        if isinstance(queries, str):
            queries = [queries]
        queries = [t.lower().strip() for t in queries]
        entries = M3UParser.parse_m3u8(m3)
        return [v for v in entries
                if v.get("tvg-id", "").lower() in queries or
                v.get("title", "").lower() in queries]


def get_duration_from_url(url):
    """ return stream duration in milliseconds """
    if not url:
        return 0
    if is_youtube(url):
        data = get_youtube_metadata(url)
        dur = data.get("length", 0)
    else:
        headers = requests.head(url).headers
        # print(headers)
        # dur = int(headers.get("Content-Length", 0))
        dur = 0
    return dur


def get_title_from_url(url):
    """ return stream duration in milliseconds """
    if url and is_youtube(url):
        data = get_youtube_metadata(url)
        return data.get("title")
    return url
