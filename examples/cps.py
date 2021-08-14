from ovos_workshop.frameworks.playback import OVOSCommonPlaybackInterface, CommonPlayMediaType
from pprint import pprint


cps = OVOSCommonPlaybackInterface(max_timeout=4, min_timeout=3)

res = cps.search_skill("skill-simple-youtube", "rob zombie",
                       media_type=CommonPlayMediaType.VIDEO)
pprint(res)
exit()
pprint(cps.search("the thing in the doorstep"))


pprint(cps.search("dagon", CommonPlayMediaType.VIDEO))

pprint(cps.search("dagon hp lovecraft"))

res = cps.search_skill("skill-news", "portuguese",
                       media_type=CommonPlayMediaType.NEWS)
if res:
    res = sorted(res["results"], key=lambda k: k['match_confidence'],
                 reverse=True)
pprint(res)
# test lovecraft skills
#pprint(common_play.search_skill("skill-omeleto", "movie",
# CommonPlayMediaType.SHORT_FILM))

