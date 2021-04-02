from os.path import join, dirname, isfile
from ovos_utils import resolve_ovos_resource_file as _resolve_utils


def resolve_workshop_resource_file(res_name):
    """Convert a resource into an absolute filename.
    used internally for ovos resources
    """
    # First look for fully qualified file (e.g. a user setting)
    if isfile(res_name):
        return res_name

    # now look in bundled ovos resources
    filename = join(dirname(__file__), "res", res_name)
    if isfile(filename):
        return filename
    filename = join(dirname(__file__), "ui", res_name)
    if isfile(filename):
        return filename
    return None  # Resource cannot be resolved


def resolve_ovos_resource_file(res_name, root_path=None, config=None):
    """Convert a resource into an absolute filename.

    Resource names are in the form: 'filename.ext'
    or 'path/filename.ext'

    The system wil look for ~/.mycroft/res_name first, and
    if not found will look at /opt/mycroft/res_name,
    then finally it will look for res_name in the 'mycroft/res'
    folder of the source code package.

    Example:
    With mycroft running as the user 'bob', if you called
        resolve_resource_file('snd/beep.wav')
    it would return either '/home/bob/.mycroft/snd/beep.wav' or
    '/opt/mycroft/snd/beep.wav' or '.../mycroft/res/snd/beep.wav',
    where the '...' is replaced by the path where the package has
    been installed.

    Args:
        res_name (str): a resource path/name
        config (dict): mycroft.conf, to read data directory from
    Returns:
        str: path to resource or None if no resource found
    """

    # First look for fully qualified file (e.g. a user setting)
    if isfile(res_name):
        return res_name
    elif root_path and isfile(join(root_path, res_name)):
        return join(root_path, res_name)

    # look in this package
    found = resolve_workshop_resource_file(res_name)
    if found:
        return found

    # look in ovos_utils package
    found = _resolve_utils(res_name)
    if found:
        return found

    return None  # Resource cannot be resolved
