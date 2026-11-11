import os
import re
import time

import requests
from dotenv import load_dotenv


load_dotenv()

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
EXCHANGERATE_API_URL = "https://v6.exchangerate-api.com/v6"
CACHE_TTL_SECONDS = 300
_rate_cache = {}

CURRENCY_NAMES = {
    "dollar": "USD",
    "dollars": "USD",
    "usd": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "eur": "EUR",
    "pound": "GBP",
    "pounds": "GBP",
    "gbp": "GBP",
    "yen": "JPY",
    "jpy": "JPY",
    "rupee": "INR",
    "rupees": "INR",
    "inr": "INR",
    "aud": "AUD",
    "cad": "CAD",
    "chf": "CHF",
    "cny": "CNY",
}


def _currency_code(value):
    code = CURRENCY_NAMES.get(value.lower())
    if code:
        return code
    if re.fullmatch(r"[A-Za-z]{3}", value):
        return value.upper()
    raise ValueError(f"Unsupported currency: {value}")


def get_exchange_rate(base_currency, target_currency, amount=1.0):
    """Return a cached live exchange rate and converted amount."""

    base = _currency_code(base_currency)
    target = _currency_code(target_currency)
    amount = float(amount)

    if amount <= 0:
        raise ValueError("Amount must be greater than zero")

    cache_key = (base, target, amount)
    cached = _rate_cache.get(cache_key)
    if cached and time.monotonic() - cached["cached_at"] < CACHE_TTL_SECONDS:
        return cached["data"]

    if base == target:
        data = {
            "base": base,
            "target": target,
            "amount": amount,
            "rate": 1.0,
            "converted_amount": amount,
            "date": None,
            "provider": "same currency",
        }
    else:
        data = _request_rate(base, target, amount)

    _rate_cache[cache_key] = {
        "cached_at": time.monotonic(),
        "data": data,
    }
    return data


def _request_rate(base, target, amount):
    try:
        response = requests.get(
            FRANKFURTER_URL,
            params={"amount": amount, "from": base, "to": target},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        converted_amount = payload["rates"][target]
        return {
            "base": base,
            "target": target,
            "amount": amount,
            "rate": converted_amount / amount,
            "converted_amount": converted_amount,
            "date": payload.get("date"),
            "provider": "Frankfurter",
        }
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        api_key = os.getenv("EXCHANGERATE_API_KEY")
        if not api_key:
            raise ValueError(
                f"Invalid or unavailable currency pair {base}/{target}: {error}"
            ) from error

        try:
            response = requests.get(
                f"{EXCHANGERATE_API_URL}/{api_key}/pair/{base}/{target}/{amount}",
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("result") != "success":
                raise ValueError(payload.get("error-type", "unknown API error"))
            return {
                "base": base,
                "target": target,
                "amount": amount,
                "rate": payload["conversion_rate"],
                "converted_amount": payload["conversion_result"],
                "date": None,
                "provider": "ExchangeRate-API",
            }
        except (requests.RequestException, KeyError, TypeError, ValueError) as fallback_error:
            raise ValueError(
                f"Unable to retrieve exchange rate for {base}/{target}: {fallback_error}"
            ) from fallback_error


def answer_currency_question(question):
    """Return a direct answer when question is a currency conversion request."""

    currency_pattern = r"(?:[A-Za-z]{3}|" + "|".join(CURRENCY_NAMES) + r")"
    conversion = re.search(
        rf"(?:convert\s+)?(?:(\d+(?:\.\d+)?)\s*)?({currency_pattern})\s+(?:to|in|into)\s+({currency_pattern})",
        question,
        re.IGNORECASE,
    )
    rate_request = re.search(
        rf"(?:exchange\s+)?rate\s+(?:from\s+)?({currency_pattern})\s+(?:to|in|against)\s+({currency_pattern})",
        question,
        re.IGNORECASE,
    )

    match = conversion or rate_request
    if not match:
        return None

    if conversion:
        amount_text, base, target = match.groups()
        amount = float(amount_text) if amount_text else 1.0
    else:
        base, target = match.groups()
        amount = 1.0

    data = get_exchange_rate(base, target, amount)
    date = f" on {data['date']}" if data["date"] else ""
    return (
        f"{data['amount']:g} {data['base']} = "
        f"{data['converted_amount']:g} {data['target']} "
        f"(1 {data['base']} = {data['rate']:g} {data['target']}, "
        f"source: {data['provider']}{date})."
    )
