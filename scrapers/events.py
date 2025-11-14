import logging
from ._common import get_soup, join
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, date

logger = logging.getLogger("scrapers.events")

def _parse_row_date(td):
    """Parse a date from a table cell (prefer hidden ISO span, fallback to visible text)."""
    if td is None:
        return None
    span = td.select_one("span.hidden")
    if span and span.get_text(strip=True):
        txt = span.get_text(strip=True)
        try:
            return datetime.fromisoformat(txt).date()
        except Exception:
            try:
                return datetime.strptime(txt.split()[0], "%Y-%m-%d").date()
            except Exception:
                pass
    visible = td.get_text(" ", strip=True)
    if visible:
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(visible, fmt).date()
            except Exception:
                continue
    return None

def scrape_events(url, events_since=None, max_pages=1):
    """
    Extract event links from table#events and filter by events_since (ISO 'YYYY-MM-DD' or date).
    Returns list of {"title","link","date": "YYYY-MM-DD", "snippet": None}.
    """
    logger.info("scrape_events: %s (since=%s)", url, events_since)
    # normalize events_since to a date
    since_date = None
    if events_since:
        if isinstance(events_since, str):
            try:
                since_date = date.fromisoformat(events_since)
            except Exception:
                try:
                    since_date = datetime.strptime(events_since, "%Y-%m-%d").date()
                except Exception:
                    since_date = None
        elif isinstance(events_since, datetime):
            since_date = events_since.date()
        elif isinstance(events_since, date):
            since_date = events_since

    soup = get_soup(url)
    table = soup.find("table", id="events")
    if not table:
        logger.debug("no table#events found at %s", url)
        return []

    items = []
    for tr in table.select("tbody tr"):
        # cells: [title, date, # entries, # drivers]
        tds = tr.find_all("td")
        if not tds:
            continue
        a = tds[0].find("a") if len(tds) >= 1 else tr.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href") or ""
        if not title or not href:
            continue

        row_date = None
        if len(tds) >= 2:
            row_date = _parse_row_date(tds[1])

        # filter by since_date if provided
        if since_date:
            if row_date:
                if row_date < since_date:
                    continue
            else:
                # cannot determine row date -> skip conservatively
                continue

        items.append({
            "title": title,
            "link": join(url, href),
            "date": row_date.isoformat() if row_date else None,
            "snippet": None,
        })

    logger.info("scrape_events found %d items", len(items))
    return items

def _find_ajax_endpoint(soup):
    import re
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"ajax\s*[:=]\s*['\"]([^'\"]+)['\"]", text)
        if m:
            return m.group(1)
        m = re.search(r"url\s*[:=]\s*['\"]([^'\"]+)['\"]", text)
        if m and "events" in m.group(1):
            return m.group(1)
    tag = soup.select_one("[data-url], [data-href], [data-src]")
    if tag:
        for attr in ("data-url", "data-href", "data-src"):
            val = tag.get(attr)
            if val:
                return val
    return None

def scrape_events_via_ajax(base_url, first_soup=None, max_pages=5):
    logger.info("attempting AJAX-based scraping for %s", base_url)
    import requests
    if first_soup is None:
        try:
            first_soup = get_soup(base_url)
        except Exception as e:
            logger.debug("failed to fetch base page: %s", e)
            return []

    endpoint = _find_ajax_endpoint(first_soup)
    if not endpoint:
        logger.debug("no ajax endpoint heuristic found for %s", base_url)
        return []

    endpoint = join(base_url, endpoint)
    results = []
    seen = set()
    parsed = urlparse(endpoint)
    base_q = parse_qs(parsed.query)

    for p in range(1, max_pages + 1):
        q = base_q.copy()
        q["page"] = [str(p)]
        candidate = parsed._replace(query=urlencode(q, doseq=True)).geturl()
        try:
            r = requests.get(candidate, timeout=10)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            evs = []
            if "application/json" in ct:
                data = r.json()
                # try to find html fragment
                text_candidate = ""
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, str) and "<table" in v:
                            text_candidate = v
                            break
                if text_candidate:
                    soup = BeautifulSoup(text_candidate, "html.parser")
                    evs = _extract_events_from_soup(soup, base_url)
                else:
                    if isinstance(data, list):
                        for it in data:
                            if isinstance(it, dict) and ("title" in it or "link" in it):
                                title = it.get("title") or it.get("name") or ""
                                link = it.get("link") or it.get("url") or ""
                                if title and link:
                                    evs.append({"title": title, "link": join(base_url, link)})
            else:
                soup = BeautifulSoup(r.text, "html.parser")
                evs = _extract_events_from_soup(soup, base_url)
            for e in evs:
                if e["link"] not in seen:
                    seen.add(e["link"])
                    results.append(e)
            if not evs:
                break
        except Exception:
            break
    logger.info("scrape_events_via_ajax found %d items", len(results))
    return results

def _extract_events_from_soup(soup, base_url):
    items = []
    table = soup.find("table", id="events")
    if not table:
        for a in soup.select("main a, #content a, .content a"):
            href = a.get("href")
            text = a.get_text(strip=True)
            if href and text:
                items.append({"title": text, "link": join(base_url, href)})
        return items
    for tr in table.select("tbody tr"):
        a = tr.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href") or ""
        if title and href:
            items.append({"title": title, "link": join(base_url, href)})
    return items

def scrape_events_with_playwright(url, max_pages=5):
    raise NotImplementedError("Use Playwright if JS-driven pagination is required.")
