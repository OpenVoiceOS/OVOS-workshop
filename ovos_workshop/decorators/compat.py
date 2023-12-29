from functools import wraps


def backwards_compat(classic_core=None, pre_008=None, no_core=None):
    """
    Decorator to run a different method if specific ovos-core versions are detected
    """

    def backwards_compat_decorator(func):
        is_classic = False
        is_old = False
        is_standalone = True
        try:
            from mycroft.version import CORE_VERSION_STR  # all classic mycroft and ovos versions
            is_classic = True
            is_standalone = False

            try:
                from ovos_core.version import OVOS_VERSION_MINOR  # ovos-core >= 0.0.8
                is_classic = False
            except ImportError:
                is_old = True
                try:
                    from mycroft.version import OVOS_VERSION_MINOR  # ovos-core <= 0.0.7
                    is_classic = False
                except:
                    is_standalone = True

        except:
            is_standalone = True

        @wraps(func)
        def func_wrapper(*args, **kwargs):
            if is_classic and callable(classic_core):
                return classic_core(*args, **kwargs)
            if is_old and callable(pre_008):
                return pre_008(*args, **kwargs)
            if is_standalone and callable(no_core):
                return no_core(*args, **kwargs)
            return func(*args, **kwargs)

        return func_wrapper

    return backwards_compat_decorator
