from ovos_workshop.frameworks.playback import OVOSCommonPlaybackInterface, MediaType
from pprint import pprint


cps = OVOSCommonPlaybackInterface()

res = cps.search_skill("skill-simple-youtube", "rob zombie",
                       media_type=MediaType.VIDEO)
pprint(res)
exit()
pprint(cps.search("the thing in the doorstep"))


pprint(cps.search("dagon", MediaType.VIDEO))

pprint(cps.search("dagon hp lovecraft"))

res = cps.search_skill("skill-news", "portuguese",
                       media_type=MediaType.NEWS)
if res:
    res = sorted(res["results"], key=lambda k: k['match_confidence'],
                 reverse=True)
pprint(res)
# test lovecraft skills
#pprint(cps.search_skill("skill-omeleto", "movie", MediaType.SHORT_FILM))

