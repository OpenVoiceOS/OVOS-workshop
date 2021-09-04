from ovos_workshop.frameworks.playback.stream_handlers.youtube import *
from ovos_workshop.frameworks.playback.stream_handlers.deezer import *
from ovos_workshop.frameworks.playback.stream_handlers.rssfeeds import *


import mimetypes


def find_mime(uri):
    """ Determine mime type. """
    mime = mimetypes.guess_type(uri)
    if mime:
        return mime
    else:
        return None
