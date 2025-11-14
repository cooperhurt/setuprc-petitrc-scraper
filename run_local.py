"""
Run the lambda handler locally.

Usage:
  # with defaults
  python run_local.py

  # specify params
  python run_local.py --track-id 1 --url "https://eatonsircr.liverc.com/events/"

Notes:
  1) Create and activate a virtualenv and install deps:
     python3 -m venv .venv
     source .venv/bin/activate
     pip install --upgrade pip
     pip install -r requirements.txt

  2) If you see ImportError, ensure the virtualenv is activated and dependencies are installed.
"""
import argparse
import json
import sys
import os
import logging

# Configure logging: console + file under ./logs/run_local.log
LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_log_file = os.path.join(LOG_DIR, "run_local.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger("run_local")


def _maybe_reexec_in_venv():
    """
    If a .venv exists in the project and the current sys.executable is NOT the venv's python,
    re-exec the script using the venv python so installed packages are visible.
    To opt out, set SKIP_VENV_REEXEC=1 in the environment.
    """
    if os.environ.get("SKIP_VENV_REEXEC") == "1":
        return

    project_venv = os.path.join(os.getcwd(), ".venv")
    venv_py = os.path.join(project_venv, "bin", "python")
    if os.path.isdir(project_venv) and os.path.isfile(venv_py):
        cur = os.path.realpath(sys.executable)
        want = os.path.realpath(venv_py)
        if cur != want:
            logger.info("Re-launching using project venv python: %s", want)
            logger.info("If you prefer to run with the current interpreter, set SKIP_VENV_REEXEC=1")
            os.execv(want, [want] + sys.argv)

# Ensure we are running under the .venv python if available
_maybe_reexec_in_venv()


def parse_args():
    p = argparse.ArgumentParser(description="Run the scraper lambda handler locally")
    p.add_argument("--track-id", type=int, default=1, help="Track ID to pass to handler")
    p.add_argument(
        "--base-url",
        type=str,
        default="https://live.liverc.com/",
        help="LiveRC base URL to scrape (landing page)",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Max pages to attempt when scraping track list",
    )
    p.add_argument(
        "--max-tracks",
        type=int,
        default=200,
        help="Limit number of tracks to import (useful for testing). Set 0 or negative for no limit.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    logger.info("Starting local run with track_id=%s base_url=%s max_pages=%s max_tracks=%s",
                args.track_id, args.base_url, args.max_pages, args.max_tracks)
    # if user passes 0 or negative, treat as no limit -> None
    max_tracks = None if args.max_tracks is None or args.max_tracks <= 0 else args.max_tracks
    event = {"track_id": args.track_id, "base_url": args.base_url, "max_pages": args.max_pages, "max_tracks": max_tracks}

    try:
        from lambda_function import lambda_handler
    except Exception as e:
        logger.exception("Failed to import lambda_function.lambda_handler")
        print("Failed to import lambda_function.lambda_handler:", file=sys.stderr)
        print(str(e), file=sys.stderr)

        # Prefer using a project .venv if present; otherwise show how to create one.
        import os
        venv_dir = os.path.join(os.getcwd(), ".venv")
        venv_python = os.path.join(venv_dir, "bin", "python")
        msg = str(e)
        missing_pkg = None
        if isinstance(e, ModuleNotFoundError) or "No module named" in msg:
            if "No module named '" in msg:
                try:
                    missing_pkg = msg.split("No module named '", 1)[1].split("'", 1)[0]
                except Exception:
                    missing_pkg = None

            print("\nIt looks like a required dependency is missing.", file=sys.stderr)

            # Map common module name to pip package
            pkg_hint = None
            if missing_pkg:
                pkg_hint = "beautifulsoup4" if missing_pkg == "bs4" else missing_pkg

            if os.path.isdir(venv_dir):
                print(
                    "You have a .venv in the project. Install into that environment with:\n"
                    f"  {venv_python} -m pip install -r requirements.txt\n",
                    file=sys.stderr,
                )
                if pkg_hint:
                    print(
                        f"Or install the missing package directly into .venv:\n"
                        f"  {venv_python} -m pip install {pkg_hint}\n",
                        file=sys.stderr,
                    )
                print(
                    "Then activate the venv for interactive use:\n"
                    "  source .venv/bin/activate\n",
                    file=sys.stderr,
                )
            else:
                print(
                    "No .venv found. Create one and install requirements:\n"
                    "  # create venv\n"
                    "  python3 -m venv .venv\n"
                    "  # install requirements using the venv's python\n"
                    "  .venv/bin/python -m pip install --upgrade pip\n"
                    "  .venv/bin/python -m pip install -r requirements.txt\n",
                    file=sys.stderr,
                )
                if pkg_hint:
                    print(
                        f"Or install the missing package directly after creating .venv:\n"
                        f"  .venv/bin/python -m pip install {pkg_hint}\n",
                        file=sys.stderr,
                    )

            print(
                "\nIf you intentionally want to install into the system interpreter shown below, run that command instead:\n"
                f"  {sys.executable} -m pip install -r requirements.txt\n",
                file=sys.stderr,
            )
        else:
            print(
                "\nHint: activate your virtualenv and install requirements:\n"
                "  source .venv/bin/activate\n"
                "  pip install -r requirements.txt\n",
                file=sys.stderr,
            )

        # Additional diagnostics: show the python executable and sys.path,
        # and try importing bs4 directly so you can see whether the running
        # interpreter can load the package.
        import sys as _sys

        print("\nDiagnostic info:", file=sys.stderr)
        print(f"Python executable: {_sys.executable}", file=sys.stderr)
        print("sys.path:", file=sys.stderr)
        for p in _sys.path:
            print(f"  {p}", file=sys.stderr)

        try:
            import bs4 as _bs4  # type: ignore
            ver = getattr(_bs4, "__version__", "unknown")
            print(f"bs4 import succeeded, version={ver}", file=sys.stderr)
        except Exception as _imp_err:
            print("bs4 import failed in this interpreter:", file=sys.stderr)
            print(f"  {_imp_err}", file=sys.stderr)
            print(
                "\nIf the interpreter above is not your .venv python, run the script with the venv python explicitly:\n"
                "  .venv/bin/python run_local.py\n"
                "Or activate the venv in your shell and re-run:\n"
                "  source .venv/bin/activate\n"
                "  python run_local.py\n",
                file=sys.stderr,
            )

        sys.exit(2)

    try:
        res = lambda_handler(event, None)
    except Exception as e:
        logger.exception("Handler raised an exception")
        print("Handler raised an exception:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(3)

    logger.info("Run finished: status=%s track_id=%s tracks_count=%s file=%s db_saved=%s",
                res.get("status"), res.get("track_id"), res.get("tracks_count"), res.get("file"), res.get("db_saved"))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
