import requests
from fastapi import FastAPI, HTTPException, Query


app = FastAPI(title="Currency Exchange API", version="1.0.0")
RATES_URL = "https://api.frankfurter.app/latest"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/exchange-rate")
def exchange_rate(
    base: str = Query("USD", min_length=3, max_length=3),
    target: str = Query("EUR", min_length=3, max_length=3),
    amount: float = Query(1.0, gt=0),
):
    base = base.upper()
    target = target.upper()

    if base == target:
        return {
            "base": base,
            "target": target,
            "amount": amount,
            "rate": 1.0,
            "converted_amount": amount,
            "source": "same currency",
        }

    try:
        response = requests.get(
            RATES_URL,
            params={"amount": amount, "from": base, "to": target},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        converted_amount = data["rates"][target]
    except (requests.RequestException, KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to retrieve exchange rate: {error}",
        ) from error

    return {
        "base": base,
        "target": target,
        "amount": amount,
        "rate": converted_amount / amount,
        "converted_amount": converted_amount,
        "date": data.get("date"),
        "source": RATES_URL,
    }