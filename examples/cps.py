from ovos_workshop.frameworks.playback import OVOSCommonPlaybackInterface, CPSMatchType
from pprint import pprint


cps = OVOSCommonPlaybackInterface(max_timeout=4, min_timeout=3)

res = cps.search_skill("skill-simple-youtube", "rob zombie",
                       media_type=CPSMatchType.VIDEO)
pprint(res)
exit()
pprint(cps.search("the thing in the doorstep"))


pprint(cps.search("dagon", CPSMatchType.VIDEO))

pprint(cps.search("dagon hp lovecraft"))

res = cps.search_skill("skill-news", "portuguese",
                       media_type=CPSMatchType.NEWS)
if res:
    res = sorted(res["results"], key=lambda k: k['match_confidence'],
                 reverse=True)
pprint(res)
# test lovecraft skills
#pprint(cps.search_skill("skill-omeleto", "movie",
# CPSMatchType.SHORT_FILM))

