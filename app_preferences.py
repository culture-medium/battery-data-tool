"""Remember folder locations locally; never persist results or selected metrics."""
import json
import os
from pathlib import Path
import tempfile

KEYS = {'battery_input', 'battery_output', 'text_input', 'text_output'}


class Preferences:
    def __init__(self, path):
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        self.values = {key: value for key, value in data.items() if key in KEYS and isinstance(value, str) and value.strip()} if isinstance(data, dict) else {}

    def get(self, key, default=''):
        return self.values.get(key, str(default))

    def initial_directory(self, key, default=None):
        for value in (self.get(key), default):
            if not value: continue
            try:
                candidate = Path(value)
                for parent in (candidate, *candidate.parents):
                    if parent.is_dir(): return str(parent)
            except (ValueError, OSError):
                continue
        return None

    def remember(self, **locations):
        updated = dict(self.values)
        for key, value in locations.items():
            if key not in KEYS: raise KeyError(key)
            value = str(value).strip()
            if not value: continue
            path = Path(value).expanduser().resolve()
            if key.endswith('_input') and not path.is_dir(): continue
            updated[key] = str(path)
        if updated == self.values: return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.folders_', suffix='.json', mode='w', encoding='utf-8', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(updated, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
            self.values = updated
        finally:
            if temporary: temporary.unlink(missing_ok=True)
