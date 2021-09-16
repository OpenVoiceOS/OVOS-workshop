import requests
import subprocess
from os.path import exists, join
from tempfile import gettempdir
from ovos_utils.log import LOG

try:
    import pafy
except ImportError:
    pafy = None


def get_youtube_live_from_channel(url):
    try:
        from youtube_searcher import extract_videos
        for e in extract_videos(url):
            if not e["is_live"]:
                continue
            return e["url"]
    except:
        pass


def get_youtube_audio_stream(url, download=False, convert=False):
    if pafy is None:
        LOG.error("can not extract audio stream, pafy is not available")
        LOG.info("pip install youtube-dl")
        LOG.info("pip install pafy")
        return {}
    stream = pafy.new(url)
    meta = {
        "url": url,
        # "audio_stream": stream.getbestaudio().url,
        # "stream": stream.getbest().url,
        "title": stream.title,
        "author": stream.author,
        "image": stream.getbestthumb().split("?")[0],
        #        "description": stream.description,
        "length": stream.length * 1000,
        "category": stream.category,
        #        "upload_date": stream.published,
        #        "tags": stream.keywords
    }
    stream = stream.getbestaudio()
    if not stream:
        return {}
    uri = stream.url
    if download:
        path = join(gettempdir(),
                    url.split("watch?v=")[-1] + "." + stream.extension)

        if not exists(path):
            stream.download(path)
        uri = path
        if convert:
            mp3 = join(gettempdir(), url.split("watch?v=")[-1] + ".mp3")
            if not exists(mp3):
                # convert file to mp3
                command = ["ffmpeg", "-n", "-i", path, "-acodec",
                           "libmp3lame", "-ab", "128k", mp3]
                subprocess.call(command)
            uri = mp3

    meta["uri"] = uri
    # try to parse artist from title
    if "-" in meta["title"]:
        removes = ["(Official Video)", "(Official Music Video)",
                   "(Lyrics)", "(Official)", "(Album Stream)", "(Legendado)"]
        removes += [s.replace("(", "").replace(")", "") for s in removes] + \
                   [s.replace("[", "").replace("]", "") for s in removes]
        removes += [s.upper() for s in removes] + [s.lower() for s in removes]
        removes += ["(HQ)", "()", "[]", "- HQ -"]
        for k in removes:
            meta["title"] = meta["title"].replace(k, "")

        meta["artist"] = meta["title"].split("-")[0]
        meta["title"] = "".join(meta["title"].split("-")[1:])
        meta["title"] = meta["title"].strip()
        meta["artist"] = meta["artist"].strip()
    return meta


def get_youtube_video_stream(url, download=False):
    if pafy is None:
        LOG.error("can not extract stream, pafy is not available")
        LOG.info("pip install youtube-dl")
        LOG.info("pip install pafy")
        return {}

    stream = pafy.new(url)

    meta = {
        "url": url,
        #"audio_stream": stream.getbestaudio().url,
        #"stream": stream.getbest().url,
        "title": stream.title,
        "author": stream.author,
        "image": stream.getbestthumb().split("?")[0],
        #        "description": stream.description,
        "length": stream.length * 1000,
        "category": stream.category,
        #        "upload_date": stream.published,
        #        "tags": stream.keywords
    }
    stream = stream.getbest()
    if not stream:
        return {}
    uri = stream.url
    if download:
        path = join(gettempdir(),
                    url.split("watch?v=")[-1] + "." + stream.extension)
        if not exists(path):
            stream.download(path)
        uri = path

    meta["uri"] = uri
    # try to parse artist from title
    if "-" in meta["title"]:
        meta["artist"] = meta["title"].split("-")[0]
        meta["title"] = "".join(meta["title"].split("-")[1:])
    return meta


def is_youtube(url):
    # TODO localization
    if not url:
        return False
    return "youtube.com/" in url or "youtu.be/" in url


def get_youtube_metadata(url):
    if pafy is None:
        LOG.error("can not extract audio stream, pafy is not available")
        LOG.info("pip install youtube-dl")
        LOG.info("pip install pafy")
        return {"url": url}
    stream = pafy.new(url)
    return {
        "url": url,
        #"audio_stream": stream.getbestaudio().url,
        #"stream": stream.getbest().url,
        "title": stream.title,
        "author": stream.author,
        "image": stream.getbestthumb().split("?")[0],
        #        "description": stream.description,
        "length": stream.length * 1000,
        "category": stream.category,
        #        "upload_date": stream.published,
        #        "tags": stream.keywords
    }


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


if __name__ == "__main__":
    print(get_youtube_live_from_channel("https://www.youtube.com/channel/UCQfwfsi5VrQ8yKZ-UWmAEFg"))
    print(get_youtube_live_from_channel(
        "https://www.youtube.com/channel/UCknLrEdhRCp1aegoMqRaCZg"))
    print(get_youtube_live_from_channel(
        "https://www.youtube.com/user/RussiaToday"))
    print(get_youtube_live_from_channel(
        "https://www.youtube.com/user/Euronews"))