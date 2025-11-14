import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging

logger = logging.getLogger("scrapers.common")

def get_soup(url, timeout=10):
    """Fetch URL and return BeautifulSoup. Raises on HTTP errors."""
    logger.debug("GET %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

# re-export urljoin for convenience
from urllib.parse import urljoin as _urljoin
def join(base, href):
    return _urljoin(base, href)
