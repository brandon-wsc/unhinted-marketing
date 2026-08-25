"""RSS adapter parses fixture XML — no network."""

from internal.perception.rss_news import parse_feed_xml

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>HK news</title>
    <item>
      <title>咖啡節周末人潮</title>
      <link>https://example.com/coffee</link>
      <guid>https://example.com/coffee</guid>
      <description>中環有市集</description>
    </item>
    <item>
      <title></title>
      <link>https://example.com/skip</link>
    </item>
  </channel>
</rss>
"""


def test_parse_feed_xml_keeps_titled_items() -> None:
    items = parse_feed_xml(FEED)
    assert len(items) == 1
    assert items[0]["title"] == "咖啡節周末人潮"
    assert items[0]["url"] == "https://example.com/coffee"
    assert items[0]["excerpt"] == "中環有市集"
    assert items[0]["key"]
