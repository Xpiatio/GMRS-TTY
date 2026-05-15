import json
import os


def load_json(filepath, default_data):
    """Helper to load JSON files safely."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error decoding {filepath}. Using defaults.")
    return default_data


def save_json(filepath, data):
    """Helper to save JSON files safely."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")
