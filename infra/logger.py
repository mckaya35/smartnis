from __future__ import annotations
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_logger(name: str = "app", logfile: str = "logs/app.log") -> logging.Logger:
    Path(logfile).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    fh = RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(JsonFormatter())
    logger.addHandler(sh)

    return logger


