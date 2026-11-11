"""Integration tests for WhatsApp Webhook and Catalogue/RAG routing.

Covers all requirements from Section 8:
- Product questions use the CSV catalogue.
- PDF questions still use the existing RAG.
- Relevant questions can use both sources.
- Unrelated WhatsApp status events are ignored.
- The existing webhook verification still works.
- Existing WhatsApp message-sending behaviour remains intact.
- External Meta API requests and LLM calls are mocked.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from whatsapp_backend.config import VERIFY_TOKEN
from whatsapp_backend.main import app
from whatsapp_backend.webhook import (
    handle_incoming_query,
    process_incoming_message,
    send_whatsapp_message,
)


class TestWebhookIntegration(unittest.TestCase):
    """Test suite covering the FastAPI webhook endpoints and routing logic."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # 1. Webhook Verification (GET /webhook)
    def test_webhook_verification_success(self):
        """Valid token and mode=subscribe returns 200 and the challenge string."""
        challenge = "random_challenge_string_98765"
        response = self.client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": challenge,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, challenge)

    def test_webhook_verification_failure_wrong_token(self):
        """Invalid verification token returns 403 Forbidden."""
        response = self.client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token_12345",
                "hub.challenge": "test_challenge",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.text, "Forbidden")

    def test_webhook_verification_failure_wrong_mode(self):
        """Invalid mode returns 403 Forbidden."""
        response = self.client.get(
            "/webhook",
            params={
                "hub.mode": "publish",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "test_challenge",
            },
        )
        self.assertEqual(response.status_code, 403)

    # 2. Unrelated status events are ignored
    def test_webhook_ignores_status_updates(self):
        """Delivery status updates (sent, delivered, read) without messages return status=ignored."""
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "123456789",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15551234567",
                                    "phone_number_id": "987654321",
                                },
                                "statuses": [
                                    {
                                        "id": "wamid.HBgLMTU1NTEyMzQ1NjcVAgASGBQz",
                                        "status": "delivered",
                                        "timestamp": "1700000000",
                                        "recipient_id": "94771234567",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }

        with patch("whatsapp_backend.webhook.process_incoming_message") as mock_process:
            response = self.client.post("/webhook", json=status_payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ignored"})
            mock_process.assert_not_called()

    # 3. Product questions route to CSV catalogue (without calling query_rag)
    @patch("whatsapp_backend.webhook.query_rag")
    def test_product_query_routes_to_catalogue(self, mock_query_rag):
        """Product catalogue queries should answer from catalogue and not invoke query_rag."""
        reply = handle_incoming_query("What is the price of the Dual Band Router?")
        mock_query_rag.assert_not_called()
        self.assertIn("Dual Band Router", reply)
        self.assertIn("8,500", reply)
        self.assertIn("R002", reply)

    @patch("whatsapp_backend.webhook.query_rag")
    def test_category_query_routes_to_catalogue(self, mock_query_rag):
        """Category listing questions should answer from catalogue and not invoke query_rag."""
        reply = handle_incoming_query("What routers are available?")
        mock_query_rag.assert_not_called()
        self.assertIn("Available *Router* devices", reply)
        self.assertIn("Basic WiFi Router", reply)

    # 4. PDF questions route to existing query_rag
    @patch("whatsapp_backend.webhook.query_rag")
    def test_pdf_query_routes_to_rag(self, mock_query_rag):
        """Questions about documents or general inquiries should invoke query_rag."""
        mock_query_rag.return_value = "According to Section 4 of the document, the warranty is 1 year."

        reply = handle_incoming_query("What is the warranty policy stated in the document?")
        mock_query_rag.assert_called_once()
        self.assertIn("According to Section 4", reply)

    # 5. Combined questions use BOTH catalogue and RAG
    @patch("whatsapp_backend.webhook.query_rag")
    def test_combined_query_uses_both_sources(self, mock_query_rag):
        """Questions asking about a product AND warranty/policy retrieve both sources."""
        mock_query_rag.return_value = "Standard manufacturer warranty is 12 months with proof of purchase."

        reply = handle_incoming_query(
            "What is the price of the Dual Band Router and what is the warranty policy?"
        )
        mock_query_rag.assert_called_once()
        self.assertIn("📦 *Product Catalogue:*", reply)
        self.assertIn("Dual Band Router", reply)
        self.assertIn("8,500", reply)
        self.assertIn("📄 *Warranty & Document Policy (from uploaded PDF):*", reply)
        self.assertIn("Standard manufacturer warranty is 12 months", reply)

    # 6. RAG failure gracefully handled without crashing
    @patch("whatsapp_backend.webhook.query_rag")
    def test_rag_missing_index_handled_gracefully(self, mock_query_rag):
        """If FAISS index is not created yet, a helpful message is returned."""
        mock_query_rag.side_effect = RuntimeError("No saved PDF index found at /path/data/faiss_index")
        reply = handle_incoming_query("What is mentioned on page 2 of the uploaded PDF?")
        self.assertIn("No PDF document has been uploaded yet", reply)

    # 7. Webhook POST queuing and outbound message sending
    @patch("whatsapp_backend.webhook.send_whatsapp_message")
    def test_process_incoming_message_executes_and_sends(self, mock_send):
        """Confirm process_incoming_message generates reply and calls send_whatsapp_message."""
        process_incoming_message("94771234567", "How many Fibre Routers are in stock?")
        mock_send.assert_called_once()
        to_number, text = mock_send.call_args[0]
        self.assertEqual(to_number, "94771234567")
        self.assertIn("4 units", text)
        self.assertIn("Fibre Router", text)

    # 8. Outbound WhatsApp sending logic and truncation
    @patch("requests.post")
    def test_send_whatsapp_message_mock(self, mock_post):
        """Confirm send_whatsapp_message formats payload, cleans recipient, and sends via requests."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"messages":[{"id":"wamid.test1234"}]}'
        mock_response.json.return_value = {"messages": [{"id": "wamid.test1234"}]}
        mock_post.return_value = mock_response

        send_whatsapp_message("+94-77-1234567", "Hello from test!")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        json_data = call_kwargs["json"]

        # Phone number must be digits only
        self.assertEqual(json_data["to"], "94771234567")
        self.assertEqual(json_data["messaging_product"], "whatsapp")
        self.assertEqual(json_data["text"]["body"], "Hello from test!")

    @patch("requests.post")
    def test_send_whatsapp_message_truncation(self, mock_post):
        """Confirm messages exceeding 4000 characters are safely truncated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"messages":[{"id":"wamid.test5678"}]}'
        mock_response.json.return_value = {"messages": [{"id": "wamid.test5678"}]}
        mock_post.return_value = mock_response

        huge_text = "A" * 5000
        send_whatsapp_message("94771234567", huge_text)

        json_data = mock_post.call_args.kwargs["json"]
        sent_body = json_data["text"]["body"]
        self.assertTrue(len(sent_body) <= 4100)
        self.assertIn("Truncated due to WhatsApp length limit", sent_body)


if __name__ == "__main__":
    unittest.main()
