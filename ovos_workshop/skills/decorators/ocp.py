from functools import wraps
from ovos_workshop.skills.layers import IntentLayers
from ovos_plugin_common_play.ocp import *


def ocp_search():
    """Decorator for adding a method as an common play search handler."""
    def real_decorator(func):
        # Store the flag inside the function
        # This will be used later to identify the method
        if not hasattr(func, 'is_ocp_search_handler'):
            func.is_ocp_search_handler = True

        return func

    return real_decorator


def ocp_play():
    """Decorator for adding a method as an common play search handler."""
    def real_decorator(func):
        # Store the flag inside the function
        # This will be used later to identify the method
        if not hasattr(func, 'is_ocp_playback_handler'):
            func.is_ocp_playback_handler = True

        return func

    return real_decorator

