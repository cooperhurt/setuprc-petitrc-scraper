import logging
from ._common import get_soup, join
from .entries import scrape_entry_list

logger = logging.getLogger("scrapers.event_page")

def scrape_event_entries(event_title, event_url):
    """
    Visit an event page, find Entry List link and extract racers.
    Returns { trackName: '', events: [...], racers: [ { name, transponder, class } ] }.
    """
    logger.info("scrape_event_entries: %s", event_url)
    event_soup = get_soup(event_url)

    entry_href = None
    clickable = event_soup.select_one('tr.clickable-row[data-href*="view_entry_list"]')
    if clickable and clickable.get("data-href"):
        entry_href = clickable.get("data-href")
    if not entry_href:
        a = event_soup.select_one('a[href*="view_entry_list"]')
        if a and a.get("href"):
            entry_href = a.get("href")

    if not entry_href:
        logger.warning("No Entry List link found on %s", event_url)
        return {"trackName": "", "events": [{"title": event_title, "link": event_url}], "racers": []}

    entry_url = join(event_url, entry_href)
    classes = scrape_entry_list(entry_url)

    racers = []
    for cl in classes:
        for r in cl.get("racers", []):
            racers.append({"name": r.get("name"), "transponder": r.get("transponder"), "class": cl.get("class")})

    result = {
        "trackName": "",
        "events": [{"title": event_title, "link": event_url, "entry_list": entry_url}],
        "racers": racers,
    }
    logger.info("scrape_event_entries: found %d racers for %s", len(racers), event_title)
    return result
