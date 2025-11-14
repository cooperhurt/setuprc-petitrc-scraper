import logging
from ._common import get_soup
logger = logging.getLogger("scrapers.entries")

def scrape_entry_list(entry_url):
    """
    Parse an entry-list page and return list of { class: 'Class Name', racers: [ { name, transponder } ] }.
    """
    logger.info("scrape_entry_list: %s", entry_url)
    soup = get_soup(entry_url)
    results = []
    for tab in soup.select(".tab-pane"):
        class_name = None
        hdr = tab.select_one(".class_header")
        if hdr and hdr.get_text(strip=True):
            class_name = hdr.get_text(strip=True)
        else:
            tab_id = tab.get("id")
            if tab_id:
                nav = soup.select_one(f'.nav-pills a[href="#{tab_id}"]')
                if nav:
                    class_name = nav.get_text(strip=True)

        table = tab.find("table")
        if not table:
            continue

        racers = []
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                driver = tds[1].get_text(" ", strip=True)
                transponder = tds[2].get_text(strip=True)
            else:
                texts = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
                if len(texts) >= 2:
                    driver = texts[1]
                    transponder = texts[2] if len(texts) > 2 else ""
                else:
                    continue
            racers.append({"name": driver, "transponder": transponder})
        results.append({"class": class_name or "", "racers": racers})
    logger.info("scrape_entry_list -> %d classes", len(results))
    return results
