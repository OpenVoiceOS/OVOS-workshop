# DEPRECATED - merged into OVOSSkill, imports for compat onlu
from ovos_workshop.skills.ovos import OVOSSkill, simple_trace, is_classic_core, SkillGUI
from ovos_utils.log import log_deprecation
from ovos_utils.process_utils import RuntimeRequirements


# backwards compat alias
class SkillNetworkRequirements(RuntimeRequirements):
    def __init__(self, *args, **kwargs):
        log_deprecation("Replace with "
                        "`ovos_utils.process_utils.RuntimeRequirements`",
                        "0.1.0")
        super().__init__(*args, **kwargs)


BaseSkill = OVOSSkill  # backwards compat

