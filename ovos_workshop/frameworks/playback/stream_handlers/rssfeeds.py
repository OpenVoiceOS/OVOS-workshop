import feedparser


def get_rss_first_stream(feed_url):
    try:
        # parse RSS or XML feed
        data = feedparser.parse(feed_url.strip())
        # After the intro, find and start the news uri
        # select the first link to an audio file

        for link in data['entries'][0]['links']:
            if 'audio' in link['type']:
                # TODO return duration for proper display in UI
                duration = link.get('length')
                return link['href']
    except Exception as e:
        pass