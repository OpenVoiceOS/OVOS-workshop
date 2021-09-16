from ovos_utils import ensure_mycroft_import
ensure_mycroft_import()

# this patch has been deprecated, imports remain for backwards compat only
# you should be using the full ovos common play framework! it now is
# packaged separately and does not need any patching
from mycroft.skills.common_play_skill import CommonPlaySkill, \
    CPSTrackStatus, CPSMatchLevel
from ovos_workshop.frameworks.playback import MediaType as CPSMatchType
from ovos_workshop.patches.base_skill import MycroftSkill
