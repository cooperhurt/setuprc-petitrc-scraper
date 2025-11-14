import re
from bs4 import BeautifulSoup

def safe_text(el):
	"""Return normalized text for an element or empty string."""
	if el is None:
		return ""
	try:
		return el.get_text(" ", strip=True)
	except Exception:
		return ""

def prefer_hidden(cell):
	"""If cell contains .hidden with useful value return that, otherwise visible text."""
	if cell is None:
		return ""
	hidden = cell.select_one(".hidden")
	if hidden and hidden.get_text(strip=True):
		return hidden.get_text(strip=True)
	return safe_text(cell)

def extract_script_text(soup):
	"""Concatenate all inline <script> text for scanning JS objects."""
	parts = []
	for s in soup.find_all("script"):
		if s.string:
			parts.append(s.string)
	return "\n".join(parts)

def parse_racerlaps_from_js(script_text):
	"""
	Parse racerLaps[ID] = { ... } blocks from JS and return mapping id -> { lap_stats, laps }.
	Produces lap_stats keys like fastLap, avgLap, consistency when present and laps list of dicts.
	"""
	out = {}
	if not script_text:
		return out

	# Find all racerLaps[<id>] = { ... };
	obj_pat = re.compile(r"racerLaps\[\s*(?P<id>\d+)\s*\]\s*=\s*(\{.*?\});", re.DOTALL)
	for m in obj_pat.finditer(script_text):
		driver_id = m.group("id")
		js_obj = m.group(2)

		def js_field(key):
			# try 'key' : 'value' patterns
			r = re.search(r"['\"]%s['\"]\s*:\s*['\"]([^'\"]*)['\"]" % re.escape(key), js_obj)
			if not r:
				r = re.search(r"%s\s*:\s*['\"]([^'\"]*)['\"]" % re.escape(key), js_obj)
			return r.group(1) if r else ""

		lap_stats = {
			"fastLap": js_field("fastLap"),
			"avgLap": js_field("avgLap"),
			"avgTop5": js_field("avgTop5"),
			"avgTop10": js_field("avgTop10"),
			"avgTop15": js_field("avgTop15"),
			"consistency": js_field("consistency"),
		}

		# Extract lap objects inside 'laps' array
		laps = []
		# accept both single and double quoted keys, tolerant whitespace
		lap_pat = re.compile(
			r"\{\s*['\"]?lapNum['\"]?\s*:\s*['\"](?P<lapNum>[^'\"]*)['\"]\s*,\s*['\"]?pos['\"]?\s*:\s*['\"](?P<pos>[^'\"]*)['\"]\s*,\s*['\"]?time['\"]?\s*:\s*['\"](?P<time>[^'\"]*)['\"]\s*,\s*['\"]?pace['\"]?\s*:\s*['\"](?P<pace>[^'\"]*)['\"][^\}]*\}",
			re.DOTALL,
		)
		for lm in lap_pat.finditer(js_obj):
			laps.append({
				"lapNum": lm.group("lapNum"),
				"pos": lm.group("pos"),
				"time": lm.group("time"),
				"pace": lm.group("pace"),
			})

		out[driver_id] = {"lap_stats": lap_stats, "laps": laps}
	return out

def find_race_result_table(soup):
	"""Return the table element for race results (prefer class selectors)."""
	tbl = soup.select_one("table.race_result, table.dataTable, table.table-striped.race_result")
	if tbl:
		return tbl
	# fallback to first table with tbody rows
	for t in soup.find_all("table"):
		if t.select("tbody tr"):
			return t
	return None
