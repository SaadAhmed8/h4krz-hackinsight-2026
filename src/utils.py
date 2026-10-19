"""
Shared utility functions for OpenAQ and Open-Meteo data pipeline.
"""
import os
import time
import logging
from typing import Dict, Any, Optional
import requests
from dotenv import load_dotenv

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pipeline")


def get_openaq_api_key() -> str:
    """Load and return OPENAQ_API_KEY from environment or .env. Raises ValueError if missing."""
    load_dotenv()
    key = os.getenv("OPENAQ_API_KEY")
    if not key or not key.strip() or key.strip() == "your_openaq_api_key_here":
        raise ValueError(
            "OPENAQ_API_KEY is not set or empty. Please set it in your .env file or environment."
        )
    return key.strip()


def safe_request(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
    timeout: int = 30
) -> requests.Response:
    """
    Perform an HTTP GET request with retries and exponential backoff for rate limits (429) and server errors (5xx).
    Never logs or leaks API keys.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp
            
            # Handle rate limiting (429) or transient server errors (500, 502, 503, 504)
            if resp.status_code in (429, 500, 502, 503, 504):
                sleep_sec = backoff_factor ** attempt
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_sec = max(sleep_sec, float(retry_after))
                
                logger.warning(
                    f"HTTP {resp.status_code} received from {url}. Retrying in {sleep_sec:.1f}s (Attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(sleep_sec)
                attempt += 1
                continue
            
            # For 4xx client errors other than 429, raise immediately
            resp.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            sleep_sec = backoff_factor ** attempt
            logger.warning(
                f"Connection/Timeout error: {type(e).__name__}. Retrying in {sleep_sec:.1f}s (Attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(sleep_sec)
            attempt += 1
        except Exception:
            raise

    # If reached here, max retries exceeded
    resp.raise_for_status()
    return resp
