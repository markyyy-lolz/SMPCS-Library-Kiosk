"""Rotating file logs for windowless launches."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

class LogStream:
    def __init__(self, logger): self.logger = logger
    def write(self, value):
        if value.strip(): self.logger.error(value.rstrip())
        return len(value)
    def flush(self): pass
    def isatty(self): return False

def configure(role):
    folder = Path(os.getenv('APPDATA', str(Path.home()))) / 'SMPCS_Library' / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('smpcs.' + role)
    if not logger.handlers:
        handler = RotatingFileHandler(folder / (role + '.log'), maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler); logger.setLevel(logging.INFO)
    sys.stdout = sys.stderr = LogStream(logger)
    logger.info('Application starting')
    return logger
