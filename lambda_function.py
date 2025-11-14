import json
import time
import logging
from scraper import scrape_tracks, scrape_track_details
from utils import save_json_to_tmp, save_to_db

logger = logging.getLogger("lambda_function")

def lambda_handler(event, context):
    """
    New handler: scrape all tracks from the LiveRC landing page and fetch details.
    Event:
      { "track_id": 1, "base_url": "https://live.liverc.com/", "max_pages": 20 }
    """
    logger.info("lambda_handler invoked with event: %s", event)
    track_id = event.get("track_id")
    base_url = event.get("base_url") or event.get("url") or "https://live.liverc.com/"
    max_pages = int(event.get("max_pages", 20))
    max_tracks = event.get("max_tracks", None)
    if isinstance(max_tracks, str) and max_tracks.isdigit():
        max_tracks = int(max_tracks)

    if track_id is None:
        logger.error("Missing required param track_id")
        return {"status": "error", "message": "Missing required param: track_id"}

    start_ts = int(time.time())

    try:
        # pass max_tracks through to scraper
        tracks = scrape_tracks(base_url=base_url, max_pages=max_pages, max_tracks=max_tracks)
        logger.info("Found %d tracks at %s (max_tracks=%s)", len(tracks), base_url, max_tracks)
    except Exception as e:
        logger.exception("scrape_tracks failed")
        return {"status": "error", "message": f"scrape_tracks failed: {e}"}

    enriched = []
    for t in tracks:
        link = t.get("link")
        try:
            details = scrape_track_details(link)
        except Exception:
            logger.exception("Failed to fetch details for %s", link)
            details = {}
        merged = {"list_name": t.get("name"), "list_snippet": t.get("snippet"), "link": link, "details": details}
        enriched.append(merged)

    result = {
        "track_id": track_id,
        "base_url": base_url,
        "scraped_at": start_ts,
        "tracks_count": len(enriched),
        "tracks": enriched,
    }

    filename = f"tracks_{track_id}_{start_ts}.json"
    filepath = save_json_to_tmp(result, filename)
    logger.info("Saved scrape JSON to %s", filepath)

    try:
        db_ok = save_to_db(result)
    except Exception:
        logger.exception("save_to_db failed")
        db_ok = False

    return {"status": "ok", "track_id": track_id, "file": filepath, "tracks_count": len(enriched), "db_saved": db_ok}