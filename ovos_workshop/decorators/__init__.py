from ovos_workshop.decorators.killable import \
    killable_intent, killable_event
from ovos_workshop.decorators.layers import enables_layer, \
    disables_layer, layer_intent, removes_layer, resets_layers, replaces_layer
from ovos_workshop.decorators.converse import converse_handler
from ovos_workshop.decorators.fallback_handler import fallback_handler


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
