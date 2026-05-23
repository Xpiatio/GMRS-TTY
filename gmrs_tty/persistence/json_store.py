import json
import logging
import os

_log = logging.getLogger(__name__)


def load_json(filepath, default_data):
    """Helper to load JSON files safely."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            _log.warning("Error decoding %s. Using defaults.", filepath)
    return default_data


def save_json(filepath, data):
    """Helper to save JSON files safely."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        _log.error("Error saving %s: %s", filepath, e)
