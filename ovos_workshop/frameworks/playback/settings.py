from ovos_workshop.frameworks.playback.status import MediaType


class CommonPlaySettings:
    # media types that can be safely cast to audio only streams when GUI is
    # not available
    cast2audio = [
        MediaType.MUSIC,
        MediaType.PODCAST,
        MediaType.AUDIOBOOK,
        MediaType.RADIO,
        MediaType.RADIO_THEATRE,
        MediaType.VISUAL_STORY,
        MediaType.NEWS
    ]
    def __init__(self, min_timeout=1, max_timeout=5,
                 allow_extensions=True, backwards_compatibility=True,
                 media_fallback=True, early_stop_conf=90,
                 early_stop_grace_period=1.0, autoplay=True,
                 force_audioservice=False):
        """
        Arguments:
            min_timeout (float): minimum time to wait for skill replies,
                                 after this time, if at least 1 result was
                                 found, selection is triggered
            max_timeout (float): maximum time to wait for skill replies,
                                 after this time, regardless of number of
                                 results, selection is triggered
            allow_extensions (bool): if True, allow skills to request more
                                     time, extend min_timeout for specific
                                     queries up to max_timeout
            backwards_compatibility (bool): if True emits the regular
                                            mycroft-core bus messages to get
                                            results from "old style" skills
            media_fallback (bool): if no results, perform a second query
                                   with MediaType.GENERIC
            early_stop_conf (int): stop collecting results if we get a
                                   match with confidence >= early_stop_conf
            early_stop_grace_period (float): sleep this amount before early stop,
                                   allows skills that "just miss" to also be
                                   taken into account
        """
        self.autoplay = autoplay
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.allow_extensions = allow_extensions
        self.media_fallback = media_fallback
        self.early_stop_thresh = early_stop_conf
        self.early_stop_grace_period = early_stop_grace_period
        self.backwards_compatibility = backwards_compatibility
        self.force_audioservice = force_audioservice

