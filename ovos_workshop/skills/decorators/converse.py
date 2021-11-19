

def converse_handler():
    """Decorator for aliasing a method as the converse method"""

    def real_decorator(func):
        if not hasattr(func, 'converse'):
            func.converse = True
        return func

    return real_decorator


def conversational_intent(intent_file):
    """Decorator for adding a method as an converse intent handler.
    NOTE: only padatious supported, not adapt
    """

    def real_decorator(func):
        # Store the intent_file inside the function
        # This will be used later to train intents
        if not hasattr(func, 'converse_intents'):
            func.converse_intents = []
        func.converse_intents.append(intent_file)
        return func

    return real_decorator
