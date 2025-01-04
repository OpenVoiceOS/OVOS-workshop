from ovos_utils.log import log_deprecation
import warnings

warnings.warn(
    "Import from `ovos_workshop.decorators`",
    DeprecationWarning,
    stacklevel=2,
)


def converse_handler(func):
    """
    Decorator for aliasing a method as the converse method
    """
    log_deprecation("Import from `ovos_workshop.decorators`", "0.1.0")
    if not hasattr(func, 'converse'):
        func.converse = True
    return func
