from ovos_utils.log import LOG

try:
    import deezeridu
except ImportError:
    deezeridu = None

from tempfile import gettempdir
from os.path import join
from os import makedirs


def get_deezer_audio_stream(url, deezer=None, path=None):
    path = path or join(gettempdir(), "deezer")
    makedirs(path, exist_ok=True)
    if deezeridu is None:
        LOG.error("can not extract deezer stream, deezeridu is not available")
        LOG.info("pip install deezeridu")
        return None
    try:
        deezer = deezer or deezeridu.Deezer()
        t = deezer.download(url, output_dir=path)
        return t.song_path
    except Exception as e:
        print(e)
        return None


def is_deezer(url):
    if not url:
        return False
    return "deezer." in url
