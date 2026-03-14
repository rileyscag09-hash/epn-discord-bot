"""
Entry point for the application.
"""
import asyncio
import sys

from EPN import run
from utils.constants import logger


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
        sys.exit()
    except Exception as e:
        logger.critical(e)
