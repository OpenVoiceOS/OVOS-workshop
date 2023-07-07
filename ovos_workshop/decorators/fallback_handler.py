from ovos_utils.log import log_deprecation


def fallback_handler(priority=50):
    log_deprecation("Import from `ovos_workshop.decorators`", "0.1.0")

    def real_decorator(func):
        if not hasattr(func, 'fallback_priority'):
            func.fallback_priority = priority
        return func

    return real_decorator
