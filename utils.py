import json
import os
import logging

logger = logging.getLogger("utils")

def save_json_to_tmp(data, filename):
	"""
	Write JSON to /tmp and also store a copy under ./scrape_results for local inspection.
	Return the /tmp path (primary for Lambda).
	"""
	# ensure /tmp write (Lambda) and local copy
	tmp_path = os.path.join("/tmp", filename)
	try:
		with open(tmp_path, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)
		logger.info("Wrote JSON to %s", tmp_path)
	except Exception as e:
		logger.exception("Failed to write JSON to /tmp: %s", e)

	# also save a local copy for debugging when running locally
	local_dir = os.path.join(os.getcwd(), "scrape_results")
	try:
		os.makedirs(local_dir, exist_ok=True)
		local_path = os.path.join(local_dir, filename)
		with open(local_path, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)
		logger.info("Wrote local JSON copy to %s", local_path)
	except Exception as e:
		logger.exception("Failed to write local JSON copy: %s", e)

	return tmp_path

def save_to_db(data):
	"""
	Placeholder for DB persistence. Implement your DB logic here.
	Currently returns False to indicate no DB write performed.
	"""
	# ...existing code...
	return False