# PDF RAG System

This Streamlit app answers questions about uploaded PDFs using Gemini embeddings, FAISS retrieval, and Gemini chat generation. `GOOGLE_API_KEY` must be a valid Gemini API key created in Google AI Studio, not an OAuth access token or Meta access token. If Google reports `API_KEY_INVALID`, create a new key at <https://aistudio.google.com/app/apikey>, replace `GOOGLE_API_KEY` in the project-root `.env`, and restart Streamlit. The application cannot repair or reactivate a key that Google has rejected. If a credential in `.env.example` was real or shared, revoke it and generate a replacement.

If PDF processing reports `getaddrinfo failed`, the machine running Streamlit could not resolve Google's API hostname. Check internet access and DNS, VPN, firewall, or proxy settings; on Windows, run `nslookup generativelanguage.googleapis.com`. If DNS resolves after the issue clears, restart Streamlit and retry the upload.

If Gemini 3.6 Flash reaches its rate limit, answer generation automatically tries Gemini 3.5 Flash; if both models are rate limited, the app reports that quota exhaustion explicitly.

## Currency exchange

The existing question box also handles currency questions such as `Convert 100 USD to EUR` or `What is the exchange rate from GBP to JPY?`. Currency questions bypass PDF retrieval and use the free Frankfurter API. Results are cached for five minutes.

If Frankfurter cannot answer a pair and `EXCHANGERATE_API_KEY` is set in `.env`, the app falls back to ExchangeRate-API. The existing `GOOGLE_API_KEY` is still required for the PDF RAG features.

## WhatsApp Cloud API webhook

The separate FastAPI webhook service lives in `whatsapp_backend/` and does not replace the Streamlit app or currency API.

1. Copy `.env.example` to `.env` and replace every placeholder with your own valid Google and Meta credentials. Set `VERIFY_TOKEN` to a private value, then enter the exact same value in Meta's webhook configuration. Keep `.env` private and do not commit it.
2. Install the project dependencies from the project root (the webhook uses the same RAG libraries as the Streamlit app):

	```powershell
	python -m pip install -r requirements.txt
	```

3. Start the webhook server:

	```powershell
	python -m uvicorn whatsapp_backend.main:app --reload --host 0.0.0.0 --port 8000
	```

	The server reads `PORT` from `.env` when launched with `python -m whatsapp_backend.main`; the uvicorn command above uses port 8000 directly.
4. In another terminal, expose the local server with ngrok:

	```powershell
	ngrok http 8000
	```

5. In the Meta Developer Portal, open your app's WhatsApp configuration and set the webhook callback URL to `https://<your-ngrok-domain>/webhook`. Enter the exact same `VERIFY_TOKEN` value as in `.env`, verify the callback, and subscribe to the `messages` webhook field. Keep the ngrok process running while testing. After changing `.env`, restart the webhook server because its settings are loaded at startup.

The GET `/webhook` route returns Meta's `hub.challenge` as plain text with HTTP 200 only when the mode is `subscribe` and the verification token matches. To test the public endpoint before submitting it in Meta, open `https://<your-ngrok-domain>/webhook?hub.mode=subscribe&hub.verify_token=<your-VERIFY_TOKEN>&hub.challenge=12345`; a successful check displays only `12345`. The POST `/webhook` route acknowledges text messages immediately, then runs the shared RAG query and sends the answer through the WhatsApp Cloud API in a background task. Recipient numbers are sent as digits only. Check the server logs for the Meta API response status; rejected requests include Meta's response details, while network failures are logged separately. A webhook HTTP 200 confirms receipt/queuing only, not successful delivery of the outbound reply. Delivery receipts and other events without text messages are acknowledged with `{"status":"ignored"}`.

The first time PDFs are processed in the Streamlit app, their FAISS index is saved under `data/faiss_index/` so the webhook process can use the same knowledge base. Set `FAISS_INDEX_PATH` in `.env` to use a different location. The WhatsApp backend also requires `META_ACCESS_TOKEN`, `PHONE_NUMBER_ID`, and `GOOGLE_API_KEY`; keep these values private. The configured FAISS index directory must be trusted because loading it uses LangChain's local pickle-backed document store.

## Run

```powershell
& "C:\Program Files\Python314\python.exe" -m pip install -r requirements.txt
& "C:\Program Files\Python314\python.exe" -m streamlit run app.py
```
