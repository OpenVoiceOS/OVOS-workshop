import youtube_dl


def get_soundcloud_audio_stream(url, prefered_ext=None):
    ydl_opts = {"quiet": True, "verbose": False}
    kmaps = {"duration": "duration",
             "thumbnail": "image",
             "uploader": "artist",
             "title": "title",
             'webpage_url': "url"}
    info = {}
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        meta = ydl.extract_info(url, download=False)
        for k, v in kmaps.items():
            info[v] = meta[k]
        info["uri"] = meta["formats"][-1]["url"]
        info["duration"] = info["duration"] * 1000  # seconds to ms
        if prefered_ext:
            for f in meta["formats"]:
                if f["ext"] == prefered_ext:
                    info["uri"] = f["url"]
                    break
    return info


def is_soundcloud(url):
    if not url:
        return False
    return "soundcloud." in url
