import enum


class ConverseMode(str, enum.Enum):
    """
    Defines a mode for handling `converse` requests.
    ACCEPT ALL - default behavior where all skills may implement `converse`
    WHITELIST - only skills explicitly allowed may implement `converse`
    BLACKLIST - all skills except those disallowed may implement `converse`
    """
    ACCEPT_ALL = "accept_all"  # Default
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class FallbackMode(str, enum.Enum):
    """
    Defines a mode for handling fallbacks (utterances without a matched intent)
    ACCEPT ALL - default behavior where all installed FallbackSkills are used
    WHITELIST - only explicitly allowed FallbackSkills may respond
    BLACKLIST - all FallbackSkills except those disallowed may respond
    """
    ACCEPT_ALL = "accept_all"  # Default
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"


class ConverseActivationMode(str, enum.Enum):
    """
    Defines a mode for manually activating `converse` handling
    ACCEPT ALL - default behavior where any skill may activate itself
    PRIORITY - a skill may only activate itself if no higher-priority skill is
        currently active
    WHITELIST - only explicitly allowed skills may activate themselves
    BLACKLIST - all skills except those disallowed may activate themselves
    """
    ACCEPT_ALL = "accept_all"  # Default
    PRIORITY = "priority"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"
