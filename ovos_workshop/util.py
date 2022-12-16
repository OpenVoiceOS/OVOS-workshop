
# TODO - move to ovos_utils
def is_ovos():
    try:
        from mycroft.version import OVOS_VERSION_STR
        return True
    except ImportError:
        return False
