"""
Run the petitrc setupsheet scraper locally.

Usage:
  # with defaults
  python run_local.py

  # specify params
  python run_local.py --url "https://www.petitrc.com/index.php?/setupsheet.html/"

Notes:
  1) Create and activate a virtualenv and install deps:
     python3 -m venv .venv
     source .venv/bin/activate
     pip install --upgrade pip
     pip install -r requirements.txt

  2) If you see ImportError, ensure the virtualenv is activated and dependencies are installed.
"""
#!/usr/bin/env python3
import argparse
import json
import logging
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Run petitrc setupsheet scraper locally")
    p.add_argument(
        "--url",
        type=str,
        default="https://www.petitrc.com/index.php?/setupsheet.html/",
        help="URL of the setupsheet index page",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("run_local")

    # ensure the 'scraper' logger follows the CLI debug flag so debug() calls inside scraper show up
    if args.debug:
        logging.getLogger("scraper").setLevel(logging.DEBUG)
    else:
        logging.getLogger("scraper").setLevel(logging.INFO)

    # reduce verbosity from third-party libraries that can drown out debug output
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        from scraper import scrape  # local module added below
    except Exception as e:
        logger.exception("Failed to import scraper module: %s", e)
        print("Failed to import scraper module:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(2)

    try:
        res = scrape(args.url)
    except Exception as e:
        logger.exception("Scraper failed: %s", e)
        print("Scraper failed:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(3)

    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
