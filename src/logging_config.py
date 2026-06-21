import logging
import sys
from contextlib import contextmanager

from tqdm import tqdm


class _TqdmHandler(logging.StreamHandler):
    """Handler que usa tqdm.write() para não quebrar barras de progresso."""

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg, file=sys.stdout)
        except Exception:
            self.handleError(record)


def setup_logging(level: int = logging.INFO) -> None:
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


@contextmanager
def tqdm_logging():
    """Redireciona logging para usar tqdm.write() durante barras de progresso."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]

    formatter = original_handlers[0].formatter if original_handlers else logging.Formatter()
    tqdm_handler = _TqdmHandler(sys.stdout)
    tqdm_handler.setFormatter(formatter)

    root.handlers = [tqdm_handler]
    try:
        yield
    finally:
        root.handlers = original_handlers
