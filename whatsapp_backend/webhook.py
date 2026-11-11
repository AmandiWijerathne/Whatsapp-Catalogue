import logging
from typing import Any

import requests
from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import PlainTextResponse

from catalogue import (
    is_catalogue_query,
    is_document_query,
    is_greeting,
    search_catalogue,
)
from rag import query_rag

from .config import META_ACCESS_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN


logger = logging.getLogger(__name__)
router = APIRouter()
WHATSAPP_MESSAGES_URL = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"
MAX_WHATSAPP_TEXT_LENGTH = 4000


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    mode: str = Query(..., alias="hub.mode"),
    verify_token: str = Query(..., alias="hub.verify_token"),
    challenge: str = Query(..., alias="hub.challenge"),
) -> PlainTextResponse:
    if mode == "subscribe" and verify_token == VERIFY_TOKEN and VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    logger.warning(
        "WhatsApp webhook verification rejected: mode_is_subscribe=%s "
        "configured_verify_token=%s",
        mode == "subscribe",
        bool(VERIFY_TOKEN),
    )
    return PlainTextResponse(content="Forbidden", status_code=403)


def send_whatsapp_message(to_phone_number: str, text: str) -> None:
    """Send a text reply through the WhatsApp Cloud API."""

    if not META_ACCESS_TOKEN:
        raise RuntimeError("META_ACCESS_TOKEN is not configured")
    if not PHONE_NUMBER_ID:
        raise RuntimeError("PHONE_NUMBER_ID is not configured")

    clean_phone_number = "".join(
        character
        for character in to_phone_number
        if character.isascii() and character.isdigit()
    )
    if not clean_phone_number:
        raise ValueError("Recipient phone number must contain digits")

    # Guard against WhatsApp 4096-character limit for text messages
    if len(text) > MAX_WHATSAPP_TEXT_LENGTH:
        text = text[:MAX_WHATSAPP_TEXT_LENGTH] + "\n\n...[Truncated due to WhatsApp length limit]"

    response = requests.post(
        WHATSAPP_MESSAGES_URL.format(phone_number_id=PHONE_NUMBER_ID),
        headers={
            "Authorization": f"Bearer {META_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone_number,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        },
        timeout=15,
    )
    response.raise_for_status()
    response_data = response.json() if response.content else {}
    msg_id = (
        response_data.get("messages", [{}])[0].get("id")
        if isinstance(response_data, dict)
        else None
    )
    logger.info(
        "WhatsApp Cloud API accepted reply: status=%s, message_id=%s",
        response.status_code,
        msg_id,
    )


def _query_rag_safe(question: str) -> str:
    """Execute a PDF RAG query with existing graceful error handling."""
    try:
        answer = query_rag(question)
        if not answer or not answer.strip():
            logger.warning("RAG query returned an empty answer")
            return "I'm sorry, I could not find relevant information in the uploaded PDF documents."
        return answer
    except RuntimeError as error:
        if "No saved PDF index found" in str(error):
            logger.warning("WhatsApp query received but no PDF index exists yet: %s", error)
            return (
                "No PDF document has been uploaded yet. Please upload and process a PDF "
                "in the Streamlit application first."
            )
        logger.exception("RuntimeError running RAG for WhatsApp: %s", error)
        return "I'm sorry, an error occurred while searching the document. Please try again."
    except Exception as error:
        logger.exception("Error running RAG for WhatsApp question '%s': %s", question, error)
        return "I'm sorry, an error occurred while processing your question. Please try again later."


def handle_incoming_query(message_text: str) -> str:
    """Identify query intent and generate an answer from Catalogue, RAG, or both."""
    text = message_text.strip()
    if not text:
        return "Please send a question about our product catalogue or uploaded PDF documents."

    if is_greeting(text):
        return (
            "Hello! 👋 Welcome to Sri Lanka Telecom product & support assistant.\n\n"
            "How can I help you today? You can ask:\n"
            "• 📦 *Product Catalogue*: Ask about routers, switches, extenders, prices, and stock "
            "(e.g., 'What routers are available?' or 'Price of Dual Band Router').\n"
            "• 📄 *PDF Documents*: Ask about warranties, policies, and information from uploaded PDFs."
        )

    has_catalogue = is_catalogue_query(text)
    has_document = is_document_query(text)

    # Combined question requiring both product catalogue data and PDF document knowledge
    if has_catalogue and has_document:
        catalogue_part = search_catalogue(text)
        rag_part = _query_rag_safe(text)
        return (
            f"📦 *Product Catalogue:*\n"
            f"{catalogue_part}\n\n"
            f"📄 *Warranty & Document Policy (from uploaded PDF):*\n"
            f"{rag_part}"
        )

    # Clear product catalogue inquiry
    if has_catalogue:
        return search_catalogue(text)

    # Default to PDF RAG pipeline for document/policy/general questions
    return _query_rag_safe(text)


def process_incoming_message(from_number: str, message_text: str) -> None:
    """Process incoming WhatsApp message, route appropriately, and send outbound reply."""

    logger.info("Processing message from %s: '%s'", from_number, message_text)

    answer = handle_incoming_query(message_text)

    try:
        send_whatsapp_message(from_number, answer)
    except requests.HTTPError as error:
        response = error.response
        if response is None:
            logger.exception("Meta API rejected WhatsApp reply without a response")
            return

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw_body": response.text}

        api_error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(api_error, dict):
            api_error = {}
        logger.error(
            "Meta API rejected WhatsApp reply: status=%s code=%s "
            "subcode=%s type=%s message=%s trace_id=%s response_body=%s",
            response.status_code,
            api_error.get("code"),
            api_error.get("error_subcode"),
            api_error.get("type"),
            api_error.get("message", "No error message returned"),
            api_error.get("fbtrace_id"),
            payload.get("raw_body", payload) if isinstance(payload, dict) else payload,
        )
    except requests.RequestException:
        logger.exception("WhatsApp Cloud API request failed")
    except Exception:
        logger.exception("Failed to send WhatsApp reply")


@router.post("/webhook")
async def receive_webhook(
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> dict[str, str]:

    # Log the complete webhook payload for debugging
    logger.info("========== WHATSAPP WEBHOOK RECEIVED ==========")
    logger.info("Payload: %s", payload)

    queued_messages = 0

    entries = payload.get("entry", [])

    if not isinstance(entries, list):
        logger.warning("Webhook payload has no valid 'entry' list")
        return {"status": "ignored"}

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        changes = entry.get("changes", [])

        if not isinstance(changes, list):
            continue

        for change in changes:
            if not isinstance(change, dict):
                continue

            value = change.get("value", {})

            if not isinstance(value, dict):
                continue

            # Log delivery statuses (sent, delivered, read, failed) from Meta
            statuses = value.get("statuses", [])
            if isinstance(statuses, list) and statuses:
                for status_info in statuses:
                    if isinstance(status_info, dict):
                        status_type = status_info.get("status")
                        recipient = status_info.get("recipient_id")
                        msg_id = status_info.get("id")
                        errors = status_info.get("errors")
                        if errors:
                            logger.error(
                                "WhatsApp delivery status: FAILED id=%s recipient=%s errors=%s",
                                msg_id,
                                recipient,
                                errors,
                            )
                        else:
                            logger.info(
                                "WhatsApp delivery status: id=%s recipient=%s status=%s",
                                msg_id,
                                recipient,
                                status_type,
                            )

            messages = value.get("messages", [])

            if not isinstance(messages, list):
                continue

            for message in messages:
                if not isinstance(message, dict):
                    continue

                logger.info("Incoming WhatsApp message object: %s", message)

                text = message.get("text", {})
                from_number = message.get("from")

                message_text = (
                    text.get("body")
                    if isinstance(text, dict)
                    else None
                )

                if (
                    not isinstance(from_number, str)
                    or not from_number
                    or not isinstance(message_text, str)
                    or not message_text.strip()
                ):
                    logger.info(
                        "Message ignored: not a valid text message"
                    )
                    continue

                logger.info(
                    "WhatsApp text message received: from=%s text=%s message_id=%s",
                    from_number,
                    message_text,
                    message.get("id"),
                )

                background_tasks.add_task(
                    process_incoming_message,
                    from_number,
                    message_text,
                )

                queued_messages += 1

    if not queued_messages:
        logger.info("No incoming user text messages in this webhook payload")
        return {"status": "ignored"}

    logger.info(
        "Successfully queued %s WhatsApp message(s)",
        queued_messages,
    )

    return {"status": "success"}