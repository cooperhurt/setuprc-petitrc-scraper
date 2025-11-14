import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
import re
import json
import tempfile
import os

logger = logging.getLogger("scraper")

# maximum number of vehicle pages to fetch setups for per brand
MAX_VEHICLE_SETUP_FETCH = 20

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

def _extract_vehicle_types(soup):
    types = set()
    for b in soup.find_all("b"):
        i = b.find("i")
        if i and i.string:
            txt = i.get_text(separator=" ", strip=True)
            # heuristic: contains a size like 1/10 or 1:10 and keywords
            if re.search(r"\b(1[:/]\d|1/\d|1:\d)\b", txt) or any(k in txt.lower() for k in ("electric","on-road","off-road","truck","pan car")):
                types.add(txt)
    return sorted(types)

def _find_vehicle_blockquote(soup):
    """
    Return the <blockquote> that lists the A..Z brand anchors for Vehicle Setups.

    Strategy:
    - Prefer the blockquote that immediately follows an element with id="Vehicle"
      or text containing "Vehicle Setups".
    - Fallback to the first blockquote that contains '#'-anchors.
    """
    # try id first
    vtag = soup.find(id="Vehicle")
    if vtag:
        bq = vtag.find_next("blockquote")
        if bq:
            return bq

    # fallback: find element whose text contains 'Vehicle Setups' (case-insensitive)
    txt_tag = None
    for tag in soup.find_all(text=True):
        if "vehicle" in tag.lower() and "setup" in tag.lower():
            txt_tag = tag
            break
    if txt_tag:
        parent = getattr(txt_tag, "parent", None)
        if parent:
            bq = parent.find_next("blockquote")
            if bq:
                return bq

    # final fallback: first blockquote that contains at least one anchor with href starting '#'
    for bq in soup.find_all("blockquote"):
        if bq.select("a[href^='#']"):
            return bq

    return None

def _extract_alphabet_brands(soup):
    """
    Parse the alphabetical block adjacent to the Vehicle header to discover brand anchors.
    Returns a dict mapping anchor-id -> display name.
    """
    out = {}
    bq = _find_vehicle_blockquote(soup)
    if not bq:
        return out

    for a in bq.select("a[href^='#']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        bid = href.lstrip("#")
        name = a.get_text(" ", strip=True)
        if bid and name:
            out[bid] = name
    return out  # id -> name

def _extract_alphabet_order(soup):
    """
    Return the ordered list of anchor ids from the Vehicle alphabetical block,
    preserving the page order (A..Z and '#' if present).
    """
    bq = _find_vehicle_blockquote(soup)
    if not bq:
        return []
    out = []
    for a in bq.select("a[href^='#']"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        bid = href.lstrip("#")
        if bid:
            out.append(bid)
    return out

def _collect_trs(soup):
    """
    Return all <tr> rows in the document.

    Rationale:
    - Some pages place brand rows outside of the largest/most "scored" table.
    - Simpler and more robust to query the whole document for <tr> rows and process them in order.
    - For debugging, write the nearest vehicle table (if found) or the full document to a temp file.
    """
    trs = soup.find_all("tr")
    logger.info("Collecting all <tr> from document: found %d rows", len(trs))

    # Debug: try to write the main vehicle table (or the full document) to a temp file for inspection
    try:
        # prefer the table immediately after the Vehicle alphabetical blockquote or Vehicle header
        tbl = None
        bq = _find_vehicle_blockquote(soup)
        if bq:
            tbl = bq.find_next("table")
        if tbl is None:
            vtag = soup.find(id="Vehicle")
            if vtag:
                tbl = vtag.find_next("table")

        content = str(tbl if tbl is not None else soup)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".html", prefix="petitrc_alltrs_", mode="w", encoding="utf-8")
        tf.write(content)
        tf.close()
        logger.info("WROTE document snippet to %s for inspection", tf.name)
    except Exception as exc:
        logger.exception("Failed to dump document snippet for debugging: %s", exc)

    return trs

# New helper: iterate through a td in document order, track last-seen "type" headings (<b><i>..</i></b>) and yield (anchor, current_type)
def _extract_links_with_types_from_td(td):
    cur_type = None
    for node in td.descendants:
        if getattr(node, "name", None):
            # detect <b> that contains an <i> or plain <b>/<strong> text used as the type label
            if node.name in ("b", "strong"):
                i = node.find("i")
                if i and i.get_text(strip=True):
                    cur_type = i.get_text(" ", strip=True)
                else:
                    txt = node.get_text(" ", strip=True)
                    if txt:
                        cur_type = txt
            # direct <i> tags sometimes appear alone
            elif node.name == "i" and node.get_text(strip=True):
                parent = node.parent
                if parent and parent.name in ("b", "font", "div"):
                    cur_type = node.get_text(" ", strip=True)
            elif node.name == "a":
                a = node
                txt = a.get_text(" ", strip=True)
                if txt:
                    # include href (may be relative) so callers can resolve it
                    yield {"name": txt, "type": cur_type or "", "href": (a.get("href") or "").strip()}
    # done

def _derive_brand_name(brand_elem, brand_td, brand_id, alpha_map):
    """
    Derive a friendly brand name from the brand element / containing td.
    Heuristics (in order):
    - alphabet anchor map lookup (alpha_map[brand_id])
    - look for <font> with size >= 5 or size attribute '5' inside brand_td
    - look for <b><i> or <i> or <b> text inside brand_elem / brand_td
    - fall back to first non-empty text line from brand_td or brand_elem
    - finally fall back to brand_id
    """
    # 1) alpha mapping (canonical)
    if alpha_map and brand_id in alpha_map:
        return alpha_map[brand_id]

    # helper to normalize candidate text
    def norm(txt):
        return txt.strip() if txt else ""

    # 2) prefer large font tags inside the td (many pages use <font size="5">)
    if brand_td:
        for f in brand_td.find_all("font"):
            sz = f.get("size") or ""
            try:
                if sz and int(re.sub(r"\D", "", sz)) >= 4:
                    t = norm(f.get_text(" ", strip=True))
                    if t:
                        return t
            except Exception:
                # non-numeric size, but maybe it is the brand
                t = norm(f.get_text(" ", strip=True))
                if t and len(t) <= 60:
                    return t

    # 3) prefer <b><i> nested patterns (brand titles)
    if brand_elem:
        b = brand_elem.find("b")
        if b:
            it = b.find("i")
            if it and it.get_text(strip=True):
                return norm(it.get_text(" ", strip=True))
            txt = b.get_text(" ", strip=True)
            if txt:
                return norm(txt)
        # direct <i> under brand_elem
        i = brand_elem.find("i")
        if i and i.get_text(strip=True):
            return norm(i.get_text(" ", strip=True))

    # 4) inspect brand_td for first reasonably short non-empty line
    if brand_td:
        txt = brand_td.get_text(separator="\n", strip=True)
        if txt:
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            for ln in lines:
                # ignore lines that look like type headings (contain numbers like 1:10 etc)
                if not re.search(r"\b(1[:/]\d|1:\d|1/\d)\b", ln):
                    if len(ln) <= 80:
                        return ln
            # fallback to first line
            return lines[0]

    # 5) last resort: brand_elem text or id
    if brand_elem:
        t = brand_elem.get_text(" ", strip=True)
        if t:
            return norm(t.splitlines()[0])
    return brand_id

def _extract_brands_and_vehicles(soup, base_url):
    # get canonical brand ids from alphabet for name fallback and ordering
    alpha_map = _extract_alphabet_brands(soup)
    alpha_order = _extract_alphabet_order(soup)
    alpha_ids = set(alpha_map.keys())

    logger.info("alpha_id=%s", alpha_ids)

    trs = _collect_trs(soup)
    logger.info("alpha_order length=%d sample=%s", len(alpha_order), alpha_order[:12])
    logger.info("alpha_map keys count=%d", len(alpha_map))
    logger.info("_collect_trs returned %d <tr> rows", len(trs))
    # quick check: show whether any selected tr contains the 'Academy' id (helps debugging)
    if "Academy" in alpha_order:
        found_academy_in_trs = any(tr.find(attrs={"id": "Academy"}) for tr in trs)
        logger.info("Academy present in selected trs? %s", found_academy_in_trs)
    # also show first few tr snippets for inspection
    for k, preview_tr in enumerate(list(trs)[:4]):
        logger.info("trs[%d] snippet: %s", k, _html_snippet(preview_tr, 300))

    brands = []
    brand_vehicles = {}

    # Build mapping from canonical brand id -> the <tr> that contains the element with that id
    id_to_tr = {}
    for bid in alpha_order:
        # 1) Prefer to find the canonical id inside the already-selected trs (stronger signal)
        found = False
        for tr in trs:
            el = tr.find(attrs={"id": bid})
            if el:
                id_to_tr[bid] = tr
                found = True
                logger.info("Found canonical id '%s' inside selected trs. element snippet: %s", bid, _html_snippet(el, 400))
                logger.info("Parent <tr> snippet: %s", _html_snippet(tr, 800))
                break
        if found:
            continue

        # 2) Fallback: look globally in the soup (older pages / odd DOMs)
        el = soup.find(id=bid)
        if el:
            tr = el.find_parent("tr")
            el_snip = _html_snippet(el, 400)
            tr_snip = _html_snippet(tr, 800) if tr is not None else "<no parent tr>"
            in_trs = (tr in trs) if tr is not None else False
            logger.info("Global lookup for canonical id '%s' found element: %s", bid, el_snip)
            logger.info("Its parent <tr> (in selected trs=%s): %s", in_trs, tr_snip)
            # only accept it if that tr is inside the chosen trs (otherwise ignore)
            if tr and in_trs:
                id_to_tr[bid] = tr
                continue

        # 3) Not found inside the selected trs — log for debugging with small context
        logger.info("canonical brand id not found inside selected trs: %s", bid)
        # show a short search context: any elements that contain the bid text as id-like
        try:
            # show nearby where the id string appears in raw HTML (if present)
            raw = str(soup)[:2000]
            if bid in raw:
                idx = raw.find(bid)
                start = max(0, idx - 120)
                end = min(len(raw), idx + 120)
                ctx = re.sub(r"\s+", " ", raw[start:end])
                logger.info("Nearby raw HTML context for '%s': %s", bid, ctx)
        except Exception:
            pass

    # Build an ordered list of (index_in_trs, bid, tr) for those we found inside the chosen trs
    ordered_brand_rows = []
    for bid in alpha_order:
        tr = id_to_tr.get(bid)
        if tr and tr in trs:
            try:
                idx = list(trs).index(tr)
            except ValueError:
                continue
            ordered_brand_rows.append((idx, bid, tr))

    # If we have at least one canonical brand row found, use that ordering to collect vehicles
    if ordered_brand_rows:
        ordered_brand_rows.sort(key=lambda x: x[0])
        logger.info("Using ordered_brand_rows (count=%d): %s", len(ordered_brand_rows),
                     [b for (_, b, _) in ordered_brand_rows])
        for n, (idx, bid, tr) in enumerate(ordered_brand_rows):
            # debug: show overview of the brand row and where we'll scan
            logger.info("Processing brand '%s' (canonical id=%s) at trs index %d", alpha_map.get(bid, bid), bid, idx)
            # derive brand name
            # find the element-with-id inside the tr (prefer the canonical element)
            brand_elem = tr.find(id=bid) or tr.find(attrs={"id": True})
            # If the element-with-id is itself the <td>, use it directly.
            if brand_elem:
                if getattr(brand_elem, "name", None) == "td":
                    brand_td = brand_elem
                else:
                    brand_td = brand_elem.find_parent("td") or (tr.find("td") if tr else None)
            else:
                brand_td = (tr.find("td") if tr else None)
            name = _derive_brand_name(brand_elem, brand_td, bid, alpha_map)

            brands.append({"id": bid, "name": name})

            # determine end index (next canonical brand row or end)
            end_idx = ordered_brand_rows[n + 1][0] if n + 1 < len(ordered_brand_rows) else len(trs)
            logger.debug("Brand '%s' scanning trs range: [%d .. %d) (count=%d)", name, idx, end_idx, max(0, end_idx - idx))
            vehicles = []
            for j in range(idx, end_idx):
                # show each tr we scan
                try:
                    tr_snip = _html_snippet(trs[j], 400)
                except Exception:
                    tr_snip = "<unavailable>"
                logger.debug("Scanning trs[%d] for brand '%s': %s", j, name, tr_snip)
                for td in trs[j].find_all("td"):
                    td_snip = _html_snippet(td, 240)
                    try:
                        # collect items from this td and log how many
                        items = list(_extract_links_with_types_from_td(td))
                    except Exception as exc:
                        logger.exception("Error extracting links from td while processing brand '%s' at trs[%d]: %s", name, j, exc)
                        items = []
                    logger.debug("trs[%d] td snippet=%s -> found %d anchors", j, td_snip, len(items))
                    for item in items:
                        vehicles.append(item)

            # dedupe while preserving order
            seen = set()
            dedup = []
            for v in vehicles:
                vn = v.get("name")
                if vn not in seen:
                    seen.add(vn)
                    dedup.append(v)
            # Resolve hrefs and fetch setups for items that have links
            fetched = 0
            for item in dedup:
                href = (item.get("href") or "").strip()
                if href:
                    # resolve absolute
                    abs_url = _ensure_abs_url(href, base_url)
                    item["url"] = abs_url
                    if fetched < MAX_VEHICLE_SETUP_FETCH:
                        try:
                            rows, pdf_url, images = _fetch_vehicle_setups(abs_url)
                            item["setups"] = rows
                            item["setup_url"] = pdf_url or ""
                            item["setup_images"] = images or []
                            fetched += 1
                            logger.info("Fetched %d setups for vehicle '%s' at %s (fetched_count=%d) images=%d pdf=%s",
                                        len(item["setups"]), item.get("name"), abs_url, fetched, len(item.get("setup_images", [])), item.get("setup_url", ""))
                        except Exception as exc:
                            logger.exception("Error fetching setups for %s: %s", abs_url, exc)
                            item["setups"] = []
                            item["setup_url"] = ""
                            item["setup_images"] = []
                    else:
                        # skip fetching further vehicle pages, keep placeholder
                        item["setups"] = []
                        item["setup_url"] = ""
                        item["setup_images"] = []
                        logger.debug("Skipping fetching setups for '%s' at %s — reached limit %d", item.get("name"), abs_url, MAX_VEHICLE_SETUP_FETCH)
                else:
                    item["url"] = ""
                    item["setups"] = []
                    item["setup_url"] = ""
                    item["setup_images"] = []
            brand_vehicles[name] = dedup

            # DOM fallback: if canonical trs-range scan found nothing, walk the document forward
            # from the canonical element and collect anchors until the next canonical id.
            if not dedup and brand_elem is not None and alpha_ids:
                logger.info("Attempting DOM-level fallback scan for brand '%s' (id=%s)", name, bid)
                fallback_items = []
                seen_names = set()
                stop_on_ids = set(alpha_ids) - {bid}
                max_steps = 20000
                steps = 0
                fetched_fb = 0
                for node in brand_elem.next_elements:
                    steps += 1
                    if steps > max_steps:
                        logger.info("DOM fallback reached max_steps=%d for brand '%s'", max_steps, name)
                        break
                    try:
                        if getattr(node, "name", None) and node.has_attr("id"):
                            nid = node.get("id")
                            if nid and nid in stop_on_ids:
                                logger.debug("DOM fallback for '%s' stopped at encountered canonical id=%s", name, nid)
                                break
                        if getattr(node, "name", None) == "a":
                            txt = node.get_text(" ", strip=True)
                            href = (node.get("href") or "").strip()
                            if txt and txt not in seen_names:
                                # attempt to recover a nearby type heading
                                ttype = ""
                                p = node
                                for _ in range(6):
                                    p = getattr(p, "parent", None)
                                    if p is None:
                                        break
                                    btag = p.find(lambda t: getattr(t, "name", None) in ("b", "i") and t.find("a") is None)
                                    if btag and btag.get_text(strip=True):
                                        ttype = btag.get_text(" ", strip=True)
                                        break
                                item = {"name": txt, "type": ttype, "href": href}
                                if href:
                                    item["url"] = _ensure_abs_url(href, base_url)
                                    if fetched_fb < MAX_VEHICLE_SETUP_FETCH:
                                        try:
                                            rows, pdf_url, images = _fetch_vehicle_setups(item["url"])
                                            item["setups"] = rows
                                            item["setup_url"] = pdf_url or ""
                                            item["setup_images"] = images or []
                                            fetched_fb += 1
                                        except Exception:
                                            item["setups"] = []
                                            item["setup_url"] = ""
                                            item["setup_images"] = []
                                    else:
                                        item["setups"] = []
                                        item["setup_url"] = ""
                                        item["setup_images"] = []
                                        logger.debug("DOM fallback skipping setups fetch for '%s' at %s — reached limit %d", txt, item["url"], MAX_VEHICLE_SETUP_FETCH)
                                else:
                                    item["url"] = ""
                                    item["setups"] = []
                                    item["setup_url"] = ""
                                    item["setup_images"] = []
                                fallback_items.append(item)
                                seen_names.add(txt)
                    except Exception:
                        continue

                if fallback_items:
                    logger.info("DOM fallback found %d anchors for brand '%s' (id=%s)", len(fallback_items), name, bid)
                    brand_vehicles[name] = fallback_items
                else:
                    logger.info("DOM fallback also found no anchors for brand '%s' (id=%s)", name, bid)
    # Also include brands found in the alphabetical block that might not have been captured above
    alpha = alpha_map  # already extracted
    existing_ids = {b["id"] for b in brands}
    for bid, bname in alpha.items():
        if bid not in existing_ids:
            brands.append({"id": bid, "name": bname})
            brand_vehicles[bname] = []

    # Ensure we always return the expected tuple even if earlier logic fell through.
    return brands, brand_vehicles

def _extract_assets_from_soup(soup, base_url):
    """Return (pdf_abs_or_empty, [abs_image_urls...]) found in the soup, resolved against base_url."""
    pdf = ""
    imgs = []
    try:
        for a in soup.find_all("a", href=True):
            ah = (a["href"] or "").strip()
            if not ah:
                continue
            if re.search(r'\.pdf($|\?)', ah, re.I) and not pdf:
                pdf = _ensure_abs_url(ah, base_url)
            if re.search(r'\.(jpe?g|png|gif|bmp)($|\?)', ah, re.I):
                imgs.append(_ensure_abs_url(ah, base_url))
        for img in soup.find_all("img", src=True):
            src = (img["src"] or "").strip()
            if src:
                imgs.append(_ensure_abs_url(src, base_url))
    except Exception:
        # be tolerant — caller will handle empties
        pass
    # dedupe while preserving order
    out = []
    seen = set()
    for u in imgs:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return (pdf or "", out)

def _fetch_vehicle_setups(vehicle_url, timeout=10):
    """
    Fetch vehicle page and extract:
      - 'setups' rows from the table (list of dicts)
        each setup dict will include:
          date, driver, driver_url (original href or absolute resolved later),
          event, composition, traction, surface, layout, source
        and will get two additional fields when available:
          setup_url (absolute PDF link from the per-driver page or "")
          setup_images (list of absolute image URLs from the per-driver page)
      - a setup PDF link found directly on the vehicle page (string, absolute URL or "")
      - a list of setup image URLs found on the vehicle page (absolute URLs list)

    Returns a tuple: (setups_rows_list, setup_pdf_href_or_empty, setup_images_list)
    """
    setups = []
    setup_pdf = ""
    setup_images = []
    try:
        logger.info("Fetching vehicle page for setups: %s", vehicle_url)
        vsoup = _get_soup(vehicle_url, timeout=timeout)
    except Exception as exc:
        logger.exception("Failed to fetch vehicle page %s: %s", vehicle_url, exc)
        return setups, setup_pdf, setup_images

    # 1) extract the setups table rows
    for table in vsoup.find_all("table"):
        header_tr = None
        for tr in table.find_all("tr"):
            header_texts = " ".join([td.get_text(" ", strip=True).lower() for td in tr.find_all(["td", "th"])])
            if all(k in header_texts for k in ("driver", "traction")) or ("driver" in header_texts and "composition" in header_texts):
                header_tr = tr
                break
        if header_tr is None:
            continue

        for tr in header_tr.find_next_siblings("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            def td_text(i):
                return tds[i].get_text(" ", strip=True) if i < len(tds) else ""
            date = td_text(0)
            driver_cell = tds[1] if len(tds) > 1 else None
            driver = ""
            driver_url = ""
            if driver_cell:
                # prefer the first anchor (many rows contain one)
                a = driver_cell.find("a")
                if a:
                    driver = a.get_text(" ", strip=True)
                    driver_url = (a.get("href") or "").strip()
                else:
                    driver = driver_cell.get_text(" ", strip=True)
            event = td_text(3) if len(tds) > 3 else td_text(2)
            # accommodate pages with slightly different column ordering by using safe lookups
            vehicle_col = td_text(2)
            composition = td_text(4) if len(tds) > 4 else ""
            layout = td_text(5) if len(tds) > 5 else ""
            traction = td_text(6) if len(tds) > 6 else (td_text(4) if composition == "" else td_text(6))
            source = td_text(7) if len(tds) > 7 else ""
            if not (driver or event or composition or traction or layout or source or date or vehicle_col):
                continue
            setups.append({
                "date": date,
                "driver": driver,
                "driver_url": driver_url,
                "vehicle": vehicle_col,
                "event": event,
                "composition": composition,
                "traction": traction,
                "layout": layout,
                "source": source,
                # per-row assets (filled below)
                "setup_url": "",
                "setup_images": [],
            })
        if setups:
            break  # prefer the first matching table

    # 2) find page-level PDF/images (e.g. manuals) on the vehicle page itself
    try:
        page_pdf, page_imgs = _extract_assets_from_soup(vsoup, vehicle_url)
        setup_pdf = page_pdf
        setup_images = page_imgs
        logger.info("Vehicle page assets for %s -> pdf=%s images=%d", vehicle_url, setup_pdf, len(setup_images))
    except Exception:
        setup_pdf = ""
        setup_images = []

    # 3) For each setup row that has a driver_url, visit that page and extract per-setup assets
    for s in setups:
        dr_href = (s.get("driver_url") or "").strip()
        if not dr_href:
            continue
        try:
            abs_dr = _ensure_abs_url(dr_href, vehicle_url)
            s["driver_url"] = abs_dr
            try:
                dsoup = _get_soup(abs_dr, timeout=timeout)
            except Exception as exc:
                logger.debug("Failed to fetch per-setup page %s: %s", abs_dr, exc)
                continue
            pdf_abs, imgs_abs = _extract_assets_from_soup(dsoup, abs_dr)
            s["setup_url"] = pdf_abs or ""
            s["setup_images"] = imgs_abs or []
            logger.info("Per-setup assets for %s -> driver=%s setup_url=%s images=%d",
                        abs_dr, s.get("driver", "<unknown>"), s["setup_url"], len(s["setup_images"]))
        except Exception as exc:
            logger.exception("Error extracting per-setup assets for %s (base %s): %s", dr_href, vehicle_url, exc)
            s["setup_url"] = ""
            s["setup_images"] = []

    return setups, (setup_pdf or ""), (setup_images or [])

def scrape(url, out_path="scrape_results/petitrc_setups.json"):
    """
    Scrape the provided petitrc setupsheet index page and return a dict:
    {
      "url": "...",
      "vehicle_types": [...],
      "brands": [{"id": "...", "name": "..."}, ...],
      "brand_vehicles": { "Brand Name": ["Vehicle A", "Vehicle B", ...], ... },
      "file": "<path to json file written>"
    }

    Writes results to `out_path` (UTF-8, pretty-printed). If out_path is None, no file is written.
    """
    logger.info("scrape: fetching %s", url)
    soup = _get_soup(url)
    vehicle_types = _extract_vehicle_types(soup)
    brands, brand_vehicles = _extract_brands_and_vehicles(soup, url)
    result = {"url": url, "vehicle_types": vehicle_types, "brands": brands, "brand_vehicles": brand_vehicles}

    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            logger.info("scrape: wrote results to %s", out_path)
            result["file"] = out_path
        except Exception as exc:
            logger.exception("scrape: failed to write output file %s: %s", out_path, exc)
            # still return the in-memory result without file key

    return result

# Export only the public scrape function
__all__ = ["scrape"]

def _html_snippet(el, maxlen=800):
	"""Return a safe truncated HTML snippet for logging."""
	if el is None:
		return ""
	try:
		h = el.prettify()
	except Exception:
		h = str(el)
	# collapse whitespace for compact logs
	h = re.sub(r"\s+", " ", h).strip()
	if len(h) > maxlen:
		return h[:maxlen] + " ...(truncated)"
	return h
