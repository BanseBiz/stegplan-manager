import json
import logging
import os

logger = logging.getLogger(__name__)

class Localization:
    """Handles application localization by loading strings from a JSON file."""
    
    def __init__(self, filepath='localization.json'):
        self.filepath = filepath
        self.strings = {}
        self.load()

    def load(self):
        """Loads the localization JSON file into memory."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.strings = json.load(f)
                logger.info(f"Loaded localization from {self.filepath}")
            except Exception as e:
                logger.error(f"Failed to load localization file: {e}")
        else:
            logger.warning(f"Localization file '{self.filepath}' not found. Fallback keys will be used.")

    def get(self, key, *args):
        """Returns the localized string for a given key, optionally formatted with provided arguments."""
        text = self.strings.get(key, key)
        if args:
            try:
                text = text.format(*args)
            except Exception as e:
                logger.error(f"Error formatting string for key '{key}': {e}")
        return text