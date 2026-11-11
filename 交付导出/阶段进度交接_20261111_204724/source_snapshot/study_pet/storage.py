"""Small local settings store. Raw media and sensor data are never collected here."""

import json
import logging
import os
from pathlib import Path
from .history import HistoryStore, local_day


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
        self.history=HistoryStore(directory,self.data.get('daily'))
        self._today_cache=None

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
        day=local_day(self.history.clock());key=(day,self.history.revision)
        if self._today_cache is None or self._today_cache[0]!=key:
            summary=self.history.summary(day,day)
            self._today_cache=(key,{'date':day,'seconds':summary['seconds'],'completed':summary['completed']})
        return dict(self._today_cache[1])

    def record(self, seconds: float, completed: bool):
        self.history.add_legacy_credit(seconds,completed)

