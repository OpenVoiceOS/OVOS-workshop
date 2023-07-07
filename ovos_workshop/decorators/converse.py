from ovos_utils.log import log_deprecation


def converse_handler(func):
    """
    Decorator for aliasing a method as the converse method
    """
    log_deprecation("Import from `ovos_workshop.decorators`", "0.1.0")
    if not hasattr(func, 'converse'):
        func.converse = True
    return func
