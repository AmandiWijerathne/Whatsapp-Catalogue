"""Unit tests for the product catalogue search module (catalogue.py).

Covers all requirements from Section 8:
1. Product ID
2. Exact product name
3. Partial product name
4. Category query
5. Price-filter query
6. Stock query
7. Unknown product
8. Empty query
9. Missing or malformed CSV file
"""

import os
import tempfile
import unittest
from pathlib import Path

from catalogue import (
    CatalogueDataError,
    CatalogueFileNotFoundError,
    Product,
    is_catalogue_query,
    is_document_query,
    is_greeting,
    load_catalogue,
    search_catalogue,
)


class TestCatalogueSearch(unittest.TestCase):
    """Test suite covering catalogue loading, searching, and query handling."""

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.catalogue_csv = cls.project_root / "catalogue.csv"

    def test_load_catalogue_success(self):
        """Confirm that catalogue.csv loads cleanly into structured Product records."""
        products = load_catalogue(self.catalogue_csv)
        self.assertEqual(len(products), 5)

        first = products[0]
        self.assertIsInstance(first, Product)
        self.assertEqual(first.product_id, "R001")
        self.assertEqual(first.product_name, "Basic WiFi Router")
        self.assertEqual(first.category, "Router")
        self.assertEqual(first.price_lkr, 4500)
        self.assertEqual(first.stock, 10)

    # 1. Product ID
    def test_query_by_product_id(self):
        """Querying by product ID returns accurate information."""
        result_r001 = search_catalogue("Tell me about R001", self.catalogue_csv)
        self.assertIn("R001", result_r001)
        self.assertIn("Basic WiFi Router", result_r001)
        self.assertIn("4,500", result_r001)

        result_r002 = search_catalogue("product R002", self.catalogue_csv)
        self.assertIn("R002", result_r002)
        self.assertIn("Dual Band Router", result_r002)
        self.assertIn("8,500", result_r002)

        result_d001 = search_catalogue("D001", self.catalogue_csv)
        self.assertIn("Network Switch", result_d001)
        self.assertIn("6,500", result_d001)

    # 2. Exact product name
    def test_query_by_exact_product_name(self):
        """Querying by exact product name returns the product's details."""
        result = search_catalogue("What is the price of the Dual Band Router?", self.catalogue_csv)
        self.assertIn("Dual Band Router", result)
        self.assertIn("8,500", result)
        self.assertIn("R002", result)
        # Ensure it does NOT dump all routers
        self.assertNotIn("Basic WiFi Router", result)
        self.assertNotIn("Fibre Router", result)

    # 3. Partial product name
    def test_query_by_partial_product_name(self):
        """Querying by partial name matches the intended product."""
        result = search_catalogue("Do you have a WiFi extender?", self.catalogue_csv)
        self.assertIn("WiFi Range Extender", result)
        self.assertIn("D002", result)
        self.assertIn("5,500", result)

        result_switch = search_catalogue("tell me about the network switch", self.catalogue_csv)
        self.assertIn("D001", result_switch)
        self.assertIn("Network Switch", result_switch)

    # 4. Category query
    def test_query_by_category(self):
        """Querying by category lists all products in that category."""
        result = search_catalogue("What routers are available?", self.catalogue_csv)
        self.assertIn("Available *Router* devices", result)
        self.assertIn("Basic WiFi Router", result)
        self.assertIn("Dual Band Router", result)
        self.assertIn("Fibre Router", result)
        # Networking devices should not be listed under router category
        self.assertNotIn("Network Switch", result)

        result_net = search_catalogue("What networking devices do you have?", self.catalogue_csv)
        self.assertIn("Network Switch", result_net)
        self.assertIn("WiFi Range Extender", result_net)

    # 5. Price-filter query
    def test_query_by_price_filter(self):
        """Price filter returns products within the specified price range."""
        result = search_catalogue("Show me products under 7000 rupees.", self.catalogue_csv)
        self.assertIn("under LKR 7,000", result)
        # Basic WiFi Router (4500), WiFi Extender (5500), Network Switch (6500)
        self.assertIn("Basic WiFi Router", result)
        self.assertIn("WiFi Range Extender", result)
        self.assertIn("Network Switch", result)
        # Dual Band (8500) and Fibre (12000) should be excluded
        self.assertNotIn("Dual Band Router", result)
        self.assertNotIn("Fibre Router", result)

        # Price filter with category constraint
        result_router_under = search_catalogue("Show me routers under 10000 rupees", self.catalogue_csv)
        self.assertIn("Basic WiFi Router", result_router_under)
        self.assertIn("Dual Band Router", result_router_under)
        self.assertNotIn("Fibre Router", result_router_under)
        self.assertNotIn("Network Switch", result_router_under)

        # Very low price filter yielding no results
        result_none = search_catalogue("products under 2000 rupees", self.catalogue_csv)
        self.assertIn("No products found under LKR 2,000", result_none)
        self.assertIn("Basic WiFi Router", result_none)  # Grounded reference to cheapest

    # 6. Stock query
    def test_query_by_stock(self):
        """Stock query returns accurate stock quantity without inventing numbers."""
        result = search_catalogue("How many Fibre Routers are in stock?", self.catalogue_csv)
        self.assertIn("4 units", result)
        self.assertIn("Fibre Router", result)
        self.assertIn("R003", result)

        result_dual = search_catalogue("is the Dual Band Router in stock?", self.catalogue_csv)
        self.assertIn("6 units", result_dual)
        self.assertIn("Dual Band Router", result_dual)

    # 7. Unknown product
    def test_query_unknown_product(self):
        """Unknown products state clearly that they cannot be found and list available items."""
        result = search_catalogue("Do you have a gaming laptop?", self.catalogue_csv)
        self.assertIn("could not find any products matching 'Do you have a gaming laptop?'", result)
        self.assertIn("Routers", result)
        self.assertIn("Networking", result)
        # Never invent false specs or pricing
        self.assertNotIn("gaming", result.lower().replace("could not find any products matching 'do you have a gaming laptop?'", ""))

    # 8. Empty query
    def test_empty_query(self):
        """Empty or whitespace queries return clear instructional guidance."""
        self.assertIn("Please provide a product name", search_catalogue("", self.catalogue_csv))
        self.assertIn("Please provide a product name", search_catalogue("   ", self.catalogue_csv))

    # 9. Missing or malformed CSV file
    def test_missing_csv_file(self):
        """Missing CSV file raises CatalogueFileNotFoundError or returns a safe error reply."""
        missing_path = self.project_root / "non_existent_catalogue.csv"
        with self.assertRaises(CatalogueFileNotFoundError):
            load_catalogue(missing_path)

        result = search_catalogue("What routers are available?", missing_path)
        self.assertIn("currently unavailable", result)

    def test_malformed_csv_file(self):
        """Malformed or headerless CSV file raises CatalogueDataError or returns safe error."""
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".csv", encoding="utf-8") as tmp:
            tmp.write("invalid_column1,invalid_column2\n1,2\n")
            tmp_path = tmp.name

        try:
            with self.assertRaises(CatalogueDataError):
                load_catalogue(tmp_path)

            result = search_catalogue("Show me products", tmp_path)
            self.assertIn("currently unavailable", result)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # Query classification helpers
    def test_query_intent_classification(self):
        """Test accuracy of query classification heuristics."""
        self.assertTrue(is_catalogue_query("What is the price of the Dual Band Router?"))
        self.assertTrue(is_catalogue_query("How many routers are available?"))
        self.assertTrue(is_catalogue_query("Show me products under 7000"))
        self.assertTrue(is_catalogue_query("D002"))

        self.assertTrue(is_document_query("What is the warranty policy?"))
        self.assertTrue(is_document_query("Can I get a refund under the return policy?"))
        self.assertTrue(is_document_query("How to install based on the PDF manual?"))

        self.assertTrue(is_greeting("Hello"))
        self.assertTrue(is_greeting("hi there"))
        self.assertFalse(is_greeting("Hello, what is the price of the router?"))


if __name__ == "__main__":
    unittest.main()
