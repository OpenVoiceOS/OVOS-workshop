from functools import wraps
from ovos_workshop.skills.layers import IntentLayers
from ovos_workshop.frameworks.playback import CommonPlayMediaType


def common_play_search():
    """Decorator for adding a method as an common play search handler."""
    def real_decorator(func):
        # Store the flag inside the function
        # This will be used later to identify the method
        if not hasattr(func, 'is_cplay_search_handler'):
            func.is_cplay_search_handler = True

        return func

    return real_decorator