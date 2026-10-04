"""decky.logger inside Decky, stdlib logging in the CLI."""
from __future__ import annotations

import logging

try:  # pragma: no cover - only available inside Decky Loader
    import decky  # type: ignore

    logger = decky.logger
except Exception:  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("allydsp")
