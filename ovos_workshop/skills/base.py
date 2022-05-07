try:
    from adapt.intent import IntentBuilder, Intent
except ImportError:
    # adapt is optional, OVOSAbstractApplication might not use intents
    IntentBuilder = Intent = None


def get_non_properties(obj):
    """Get attibutes that are not properties from object.

    Will return members of object class along with bases down to MycroftSkill.

    Args:
        obj: object to scan

    Returns:
        Set of attributes that are not a property.
    """

    def check_class(cls):
        """Find all non-properties in a class."""
        # Current class
        d = cls.__dict__
        np = [k for k in d if not isinstance(d[k], property)]
        # Recurse through base classes excluding MycroftSkill and object
        for b in [b for b in cls.__bases__ if b.__name__ not in ("object", "MycroftSkill")]:
            np += check_class(b)
        return np

    return set(check_class(obj.__class__))

