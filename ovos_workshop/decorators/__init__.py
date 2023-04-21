from ovos_workshop.decorators.killable import killable_intent, killable_event
from ovos_workshop.decorators.layers import enables_layer, \
    disables_layer, layer_intent, removes_layer, resets_layers, replaces_layer
from ovos_workshop.decorators.converse import converse_handler
from ovos_workshop.decorators.fallback_handler import fallback_handler
from ovos_utils import classproperty
from functools import wraps
try:
    from ovos_workshop.decorators.ocp import ocp_next, ocp_play, ocp_pause, ocp_resume, ocp_search, ocp_previous, ocp_featured_media
except ImportError:
    pass  # these imports are only available if extra requirements are installed

"""
Decorators for use with MycroftSkill methods

Helper decorators for handling context from skills.
"""


def adds_context(context, words=''):
    """Decorator adding context to the Adapt context manager.

    Args:
        context (str): context Keyword to insert
        words (str): optional string content of Keyword
    """

    def context_add_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            ret = func(*args, **kwargs)
            args[0].set_context(context, words)
            return ret

        return func_wrapper

    return context_add_decorator


def removes_context(context):
    """Decorator removing context from the Adapt context manager.

    Args:
        context (str): Context keyword to remove
    """

    def context_removes_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **kwargs):
            ret = func(*args, **kwargs)
            args[0].remove_context(context)
            return ret

        return func_wrapper

    return context_removes_decorator


def intent_handler(intent_parser):
    """Decorator for adding a method as an intent handler."""

    def real_decorator(func):
        # Store the intent_parser inside the function
        # This will be used later to call register_intent
        if not hasattr(func, 'intents'):
            func.intents = []
        func.intents.append(intent_parser)
        return func

    return real_decorator


def intent_file_handler(intent_file):
    """Decorator for adding a method as an intent file handler.

    This decorator is deprecated, use intent_handler for the same effect.
    """

    def real_decorator(func):
        # Store the intent_file inside the function
        # This will be used later to call register_intent_file
        if not hasattr(func, 'intent_files'):
            func.intent_files = []
        func.intent_files.append(intent_file)
        return func

    return real_decorator


def resting_screen_handler(name):
    """Decorator for adding a method as an resting screen handler.

    If selected will be shown on screen when device enters idle mode.
    """

    def real_decorator(func):
        # Store the resting information inside the function
        # This will be used later in register_resting_screen
        if not hasattr(func, 'resting_handler'):
            func.resting_handler = name
        return func

    return real_decorator


def skill_api_method(func):
    """Decorator for adding a method to the skill's public api.

    Methods with this decorator will be registered on the message bus
    and an api object can be created for interaction with the skill.
    """
    # tag the method by adding an api_method member to it
    if not hasattr(func, 'api_method') and hasattr(func, '__name__'):
        func.api_method = True
    return func
