import logging
import uvicorn
from fastapi import FastAPI

from .config import PORT
from .webhook import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="WhatsApp Cloud API Webhook")
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("whatsapp_backend.main:app", host="0.0.0.0", port=PORT)
