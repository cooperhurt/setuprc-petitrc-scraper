# setuprc-liver-scraper

Small Lambda scraper for live.liverc.com (or other pages).

Example event:
{ "track_id": 1, "url": "https://eatonsircr.liverc.com/events/" }

Short guide: create a venv, install deps, and run a local test.

1) Create the virtual environment
- macOS / Linux:
  python3 -m venv .venv
- Windows (PowerShell):
  python -m venv .venv

2) Activate the virtual environment
- macOS / Linux:
  source .venv/bin/activate
- Windows (PowerShell):
  .venv\Scripts\Activate.ps1
- Windows (cmd.exe):
  .venv\Scripts\activate.bat

3) Upgrade pip and install requirements
- pip install --upgrade pip
- pip install -r requirements.txt

4) Test locally
- create or run your local test script, e.g.:
  python run_local.py

5) Helper script
- Use scripts/setup_venv.sh to create the venv and install requirements automatically on Unix-like systems:
  bash scripts/setup_venv.sh

Notes:
- Lambda uses its own environment; for deployment package include dependencies or use a layer.
- The venv folder (.venv) should be added to .gitignore.

Packaging for Lambda:
- Include dependencies (pip install -r requirements.txt -t ./package)
- Zip package contents and upload or use Lambda layers.

When to use BeautifulSoup vs a headless browser
- BeautifulSoup + requests: best when the server returns full HTML (static pages) or when there is an API/AJAX endpoint you can call directly.
- Inspect DevTools (Network tab) while clicking pagination/Next: if you see XHR/fetch requests returning JSON or HTML fragments, call that endpoint with requests — much faster and Lambda-friendly.
- If clicking Next only runs client-side JS and no network request is made (page state is changed entirely in-browser), use a headless browser (Playwright or Selenium) to emulate clicks.

Quick workflow to decide:
1) Open the page in browser DevTools -> Network. Click Next. Do you see an XHR/fetch? If yes: copy that request, reproduce with requests.
2) If no XHR and only JS DOM updates: use Playwright.

Playwright quick install (local):
- pip install playwright
- python -m playwright install

Playwright on AWS Lambda:
- Use playwright-aws-lambda or a Lambda Layer containing Chromium and Playwright.
- Playwright increases deployment complexity and package size; prefer calling AJAX endpoints if possible.

Examples:
- Try requests + BeautifulSoup first (existing scrape_events).
- If you get only the first page of events, run the helper scrape_events_via_ajax(url) which attempts to find an endpoint.
- If that fails, implement scrape_events_with_playwright using Playwright to click pagination and collect event links.

Quick fix when activation appears to not take effect
- If you've activated the venv but the script still runs under a different Python, run the script explicitly with the venv python:
  .venv/bin/python run_local.py

- The run_local.py automatically re-launches itself using .venv/bin/python when a .venv exists. If you want to skip that behavior, set:
  SKIP_VENV_REEXEC=1 python run_local.py

Troubleshooting interpreter / dependency mismatch
- If you see "No module named 'bs4'" even after activating the venv, run these checks:

  # which python is being used in this shell
  which python
  # or on macOS zsh:
  type python

  # explicit venv python version and path
  .venv/bin/python -V
  .venv/bin/python -c "import sys; print(sys.executable)"

  # verify bs4 is installed in the venv python
  .venv/bin/python -c "import bs4; print(bs4.__version__)"

- If the .venv python works, run the script explicitly with it:
  .venv/bin/python run_local.py

- Note: run_local.py will normally re-launch itself in .venv if it detects a mismatch. If you set SKIP_VENV_REEXEC=1, that auto re-exec is skipped — then be sure you are invoking the .venv python explicitly as shown above.

- If activation does not update PATH, double-check your shell configuration (zshrc / bashrc) and ensure you are sourcing the correct activate script:
  source .venv/bin/activate

Shell alias / interpreter troubleshooting (you saw: "python: aliased to /usr/bin/python3")
- Problem: if your shell has an alias or function for "python" (e.g. in ~/.zshrc), that alias takes precedence over the venv activate script. Activation adds .venv/bin to PATH, but aliases are checked first by the shell.

Quick checks to run in your shell:
- Show alias / how python resolves:
  alias python
  type python
  type -a python
  command -v python
- Show PATH order (ensure .venv/bin is first when activated):
  echo $PATH

Commands to fix or work around immediately:
- Run the venv python explicitly (recommended):
  .venv/bin/python run_local.py
- Or install / run commands with venv python:
  .venv/bin/python -m pip install -r requirements.txt
- Remove the alias for the current session:
  unalias python
- Or bypass aliases for a single invocation:
  command python run_local.py
- After activating, clear the shell command cache (zsh/bash):
  hash -r

Permanent fix:
- Remove or edit the alias in your shell rc (~/.zshrc, ~/.bashrc, ~/.profile). Look for a line like:
  alias python='/usr/bin/python3'
  and remove it (or make it conditional).

Verification steps (after fix or explicit invocation):
- .venv/bin/python -V
- .venv/bin/python -c "import bs4; print(bs4.__version__)"
- .venv/bin/python run_local.py

If you try one of the explicit commands above and paste the output (.venv/bin/python -V and the import bs4 check), I’ll help you interpret it.