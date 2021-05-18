from functools import wraps
from ovos_workshop.skills.layers import IntentLayers


def enables_layer(layer_name):
    def layer_handler(func):
        @wraps(func)
        def call_function(*args, **kwargs):
            skill = args[0]
            skill.intent_layers = skill.intent_layers or \
                                  IntentLayers().bind(skill)
            func()
            skill.intent_layers.activate_layer(layer_name)

        return call_function

    return layer_handler


def disables_layer(layer_name):
    def layer_handler(func):
        @wraps(func)
        def call_function(*args, **kwargs):
            skill = args[0]
            skill.intent_layers = skill.intent_layers or \
                                  IntentLayers().bind(skill)
            func()
            skill.intent_layers.deactivate_layer(layer_name)

        return call_function

    return layer_handler


def replaces_layer(layer_name, intent_list):
    def layer_handler(func):
        @wraps(func)
        def call_function(*args, **kwargs):
            skill = args[0]
            skill.intent_layers = skill.intent_layers or \
                                  IntentLayers().bind(skill)
            func()
            skill.intent_layers.replace_layer(layer_name, intent_list)

        return call_function

    return layer_handler


def removes_layer(layer_name, intent_list):
    def layer_handler(func):
        @wraps(func)
        def call_function(*args, **kwargs):
            skill = args[0]
            skill.intent_layers = skill.intent_layers or \
                                  IntentLayers().bind(skill)
            func()
            skill.intent_layers.replace_layer(layer_name, intent_list)

        return call_function

    return layer_handler


def resets_layers():
    def layer_handler(func):
        @wraps(func)
        def call_function(*args, **kwargs):
            skill = args[0]
            skill.intent_layers = skill.intent_layers or \
                                  IntentLayers().bind(skill)
            func()
            skill.intent_layers.disable()

        return call_function

    return layer_handler


def layer_intent(intent_parser, layer_name):
    """Decorator for adding a method as an intent handler belonging to an
    intent layer."""

    def real_decorator(func):
        # Store the intent_parser inside the function
        # This will be used later to call register_intent
        if not hasattr(func, 'intents'):
            func.intents = []
        if not hasattr(func, 'intent_layers'):
            func.intent_layers = {}

        func.intents.append(intent_parser)
        if layer_name not in func.intent_layers:
            func.intent_layers[layer_name] = []

        # get intent_name
        if hasattr(intent_parser, "build"):
            intent = intent_parser.build()
            intent_name = intent.name or func.__name__
        elif hasattr(intent_parser, "name"):
            intent_name = intent_parser.name
        else:
            intent_name = intent_parser

        func.intent_layers[layer_name].append(intent_name)
        return func

    return real_decorator
