import requests
import subprocess
from os.path import exists, join
from tempfile import gettempdir
from ovos_utils.log import LOG

try:
    import pafy
except ImportError:
    pafy = None


def get_youtube_audio_stream(url, download=False, convert=False):
    if pafy is None:
        LOG.error("can not extract audio stream, pafy is not available")
        LOG.info("pip install youtube-dl")
        LOG.info("pip install pafy")
        return url
    try:
        stream = pafy.new(url)
    except:
        return None
    stream = stream.getbestaudio()
    if not stream:
        return None

    if download:
        path = join(gettempdir(),
                    url.split("watch?v=")[-1] + "." + stream.extension)

        if not exists(path):
            stream.download(path)

        if convert:
            mp3 = join(gettempdir(), url.split("watch?v=")[-1] + ".mp3")
            if not exists(mp3):
                # convert file to mp3
                command = ["ffmpeg", "-n", "-i", path, "-acodec",
                           "libmp3lame", "-ab", "128k", mp3]
                subprocess.call(command)
            return mp3

        return path

    return stream.url


def get_youtube_video_stream(url, download=False):
    if pafy is None:
        LOG.error("can not extract audio stream, pafy is not available")
        LOG.info("pip install youtube-dl")
        LOG.info("pip install pafy")
        return url
    try:
        stream = pafy.new(url)
    except:
        return None
    stream = stream.getbest()
    if not stream:
        return None

    if download:
        path = join(gettempdir(),
                    url.split("watch?v=")[-1] + "." + stream.extension)
        if not exists(path):
            stream.download(path)
        return path
    return stream.url


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
        return url
    try:
        stream = pafy.new(url)
    except:
        return {}
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
