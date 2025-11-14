import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import re

logger = logging.getLogger("scraper")

def _get_soup(url, timeout=10):
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def _ensure_abs_url(href, base_url):
    """Normalize URLs like //host..., /path or relative into an absolute https URL."""
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base_url, href)

def _extract_tracks_from_soup(soup, base_url):
    """
    Extract track rows from the landing-page soup.
    Returns list of { name, link, snippet }.
    """
    out = []
    for tr in soup.select("tr.clickable-row, table.track_list tbody tr"):
        try:
            href = tr.get("data-href") or ""
            if not href:
                a = tr.select_one("td a, a")
                href = a.get("href") if a and a.has_attr("href") else ""
            link = _ensure_abs_url(href, base_url)

            name_el = tr.select_one("td a strong") or tr.select_one("td a") or tr.select_one("strong")
            name = name_el.get_text(" ", strip=True) if name_el else (tr.get_text(" ", strip=True) or "")

            sn = ""
            indent_small = tr.select_one("td .indent small")
            if indent_small:
                sn = indent_small.get_text(" ", strip=True)
            else:
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    small = tds[1].select_one("small")
                    if small:
                        sn = small.get_text(" ", strip=True)

            if name and link:
                out.append({"name": name, "link": link, "snippet": sn})
        except Exception:
            continue
    return out

def scrape_tracks(base_url="https://live.liverc.com/", max_pages=20, max_tracks=None):
    """
    Scrape all tracks from the LiveRC landing page.
    Returns list of { name, link, snippet } (links are absolute).
    max_tracks: optional int - stop after collecting this many tracks (useful for tests).
    """
    logger.info("scrape_tracks: fetching %s", base_url)
    try:
        soup = _get_soup(base_url)
    except Exception as e:
        logger.exception("scrape_tracks: failed to fetch landing page %s", e)
        return []

    tracks = _extract_tracks_from_soup(soup, base_url)
    # enforce initial limit if provided
    if isinstance(max_tracks, int) and max_tracks >= 0 and len(tracks) > max_tracks:
        return tracks[:max_tracks]
    seen = {t["link"] for t in tracks}

    # Try to detect simple pagination links and request subsequent pages.
    pag = soup.select_one("#DataTables_Table_0_paginate, .dataTables_paginate")
    pages = []
    if pag:
        for a in pag.select("a"):
            txt = a.get_text(strip=True)
            if txt.isdigit():
                try:
                    pages.append(int(txt))
                except Exception:
                    continue
    pages = sorted(set(pages))
    if not pages:
        # still enforce limit
        if isinstance(max_tracks, int) and max_tracks >= 0:
            return tracks[:max_tracks]
        return tracks

    # attempt basic ?page=N and ?start=offset variants
    page_size = 10
    pl = soup.select_one("select[name^='DataTables_Table_0_length']")
    if pl:
        try:
            opt = pl.find("option", selected=True) or pl.find("option")
            if opt and opt.has_attr("value"):
                page_size = int(opt["value"])
        except Exception:
            page_size = 10

    from urllib.parse import urlparse
    parsed_base = urlparse(base_url)

    # helper to stop when reaching max_tracks
    def _reached_limit():
        return isinstance(max_tracks, int) and max_tracks >= 0 and len(tracks) >= max_tracks

    for p in pages:
        if p == 1:
            continue
        if _reached_limit():
            break
        if len(tracks) >= max_pages * page_size:
            break
        try_urls = []
        qpage = parsed_base._replace(query=f"page={p}").geturl()
        try_urls.append(qpage)
        start_offset = (p - 1) * page_size
        qstart = parsed_base._replace(query=f"start={start_offset}").geturl()
        try_urls.append(qstart)

        for u in try_urls:
            if _reached_limit():
                break
            try:
                r = requests.get(u, timeout=10)
                r.raise_for_status()
                s2 = BeautifulSoup(r.text, "html.parser")
                found_any = False
                for t in _extract_tracks_from_soup(s2, base_url):
                    if t["link"] not in seen:
                        tracks.append(t); seen.add(t["link"]); found_any = True
                        if _reached_limit():
                            break
                if found_any:
                    break
            except Exception:
                continue

    # final trim in case we've slightly over-collected
    if isinstance(max_tracks, int) and max_tracks >= 0:
        return tracks[:max_tracks]
    return tracks

def scrape_track_details(track_url):
    """
    Fetch a track page and extract:
    { name, address: {...}, phone, website, email, description, video_feed, scoring_feed }
    """
    logger.info("scrape_track_details: %s", track_url)
    abs_url = _ensure_abs_url(track_url, "https://live.liverc.com/")
    try:
        soup = _get_soup(abs_url)
    except Exception as e:
        logger.exception("scrape_track_details: failed to fetch %s", e)
        return {}

    out = {"name": "", "address": {}, "phone": "", "website": "", "email": "", "description": "", "video_feed": "", "scoring_feed": ""}

    about_panel = None
    for panel in soup.select("div.panel"):
        h = panel.select_one(".panel-heading")
        if h and "about" in (h.get_text(" ", strip=True) or "").lower():
            about_panel = panel
            break

    if not about_panel:
        title = soup.select_one("h1, .panel-heading, strong, title")
        out["name"] = title.get_text(" ", strip=True) if title else ""
    else:
        h = about_panel.select_one(".panel-heading")
        if h:
            txt = h.get_text(" ", strip=True)
            m = re.sub(r"^about\s*", "", txt.strip(), flags=re.I)
            out["name"] = m.strip()

        panel_body = about_panel.select_one(".panel-body") or about_panel
        addr_el = panel_body.select_one("address.small")
        if addr_el:
            lines = [l.strip() for l in addr_el.get_text("\n", strip=True).splitlines() if l.strip()]
            raw_lines = lines.copy()

            phone_el = addr_el.select_one("a[href^='tel:']")
            address_phone = phone_el.get_text(" ", strip=True) if phone_el else ""

            site_el = None
            for a in addr_el.select("a"):
                href = a.get("href") or ""
                if href.startswith("http"):
                    site_el = a
                    break
            website = site_el.get("href") if site_el else ""

            email = ""
            email_anchor = addr_el.select_one("a[href^='javascript:noSpam'], a[onclick]")
            if email_anchor and (email_anchor.has_attr("href") or email_anchor.has_attr("onclick")):
                href = email_anchor.get("href", "") or email_anchor.get("onclick", "")
                m = re.search(r"noSpam\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", href)
                if m:
                    email = f"{m.group(1)}@{m.group(2)}"
            if not email:
                m2 = addr_el.select_one("a[href^='mailto:']")
                if m2:
                    email = m2.get("href").split(":", 1)[-1]

            street = city = state = postal = country = ""
            if raw_lines:
                if raw_lines and out["name"] and raw_lines[0].lower().startswith(out["name"].lower()):
                    raw_lines = raw_lines[1:]
                if len(raw_lines) >= 1:
                    street = raw_lines[0]
                if len(raw_lines) >= 2:
                    csz = raw_lines[1]
                    parts = [p.strip() for p in csz.split(",") if p.strip()]
                    if len(parts) >= 2:
                        city = parts[0]
                        rest = parts[1]
                        mst = re.match(r"([^0-9]+)\s*([0-9\-]*)", rest)
                        if mst:
                            state = mst.group(1).strip()
                            postal = mst.group(2).strip()
                        else:
                            state = rest
                    else:
                        city = csz
                if len(raw_lines) >= 3:
                    country = raw_lines[2]

            address = {
                "street": street,
                "city": city,
                "state": state,
                "postal": postal,
                "country": country,
                "raw_lines": raw_lines,
            }
            out["address"] = address
            out["phone"] = address_phone or ""
            out["website"] = website or ""
            out["email"] = email or ""

        desc_block = panel_body.select_one(".row .col-md-12")
        if desc_block:
            for rem in desc_block.select("address, img, iframe"):
                rem.extract()
            desc = desc_block.get_text(" ", strip=True)
        else:
            pb_copy = panel_body
            if addr_el:
                addr_el.extract()
            desc = pb_copy.get_text(" ", strip=True)
        out["description"] = desc

    root_base = abs_url.rstrip("/")
    if root_base.lower().endswith("/live"):
        root_base = root_base[: -len("/live")]
    out["video_feed"] = root_base + "/live/video/"
    out["scoring_feed"] = root_base + "/live/scoring"

    if not out["name"]:
        title = soup.select_one("title")
        if title:
            out["name"] = title.get_text(" ", strip=True)

    return out

# Export the functions defined in this module
__all__ = ["scrape_tracks", "scrape_track_details"]
