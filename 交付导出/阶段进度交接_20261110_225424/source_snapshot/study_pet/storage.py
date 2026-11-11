"""Small local settings store. Raw media and sensor data are never collected here."""

from datetime import date
import json
import logging
import os
from pathlib import Path


class Store:
    def __init__(self, directory: Path):
        self.path = directory / "settings.json"
        self.data = {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                self.data = value
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self, **values):
        self.data.update(values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
        except OSError:
            logging.exception("Could not save settings")

    def today(self):
        stats = self.get("daily", {})
        if not isinstance(stats, dict) or stats.get("date") != date.today().isoformat():
            return {"date": date.today().isoformat(), "seconds": 0, "completed": 0}
        try:
            return {"date": stats["date"], "seconds": max(0, int(stats.get("seconds", 0))),
                    "completed": max(0, int(stats.get("completed", 0)))}
        except (ValueError, TypeError):
            return {"date": date.today().isoformat(), "seconds": 0, "completed": 0}

    def record(self, seconds: float, completed: bool):
        stats = self.today()
        stats["seconds"] += max(0, int(seconds))
        stats["completed"] += int(completed)
        self.save(daily=stats)

