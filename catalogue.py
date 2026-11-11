"""Product Catalogue search and query module.

Loads networking products from catalogue.csv and provides structured,
case-insensitive searching, price filtering, stock checking, and
WhatsApp-friendly formatted responses.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from whatsapp_backend.config import CATALOGUE_CSV_PATH

logger = logging.getLogger(__name__)


class CatalogueError(Exception):
    """Base exception for catalogue-related errors."""


class CatalogueFileNotFoundError(CatalogueError):
    """Raised when the catalogue CSV file cannot be found."""


class CatalogueDataError(CatalogueError):
    """Raised when the catalogue CSV data is corrupt or unreadable."""


@dataclass(frozen=True)
class Product:
    """Structured record representing a single product in the catalogue."""

    product_id: str
    product_name: str
    category: str
    brand: str
    price_lkr: int
    stock: int
    description: str
    specifications: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the product record to a standard dictionary."""
        return asdict(self)

    def format_card(self) -> str:
        """Format the complete product card for WhatsApp."""
        return (
            f"*{self.product_id} — {self.product_name}*\n"
            f"• Category: {self.category}\n"
            f"• Brand: {self.brand}\n"
            f"• Price: LKR {self.price_lkr:,}\n"
            f"• Stock: {self.stock} units available\n"
            f"• Description: {self.description}\n"
            f"• Specifications: {self.specifications}"
        )

    def format_summary_line(self) -> str:
        """Format a single-line summary of the product."""
        return (
            f"• *{self.product_name}* (ID: {self.product_id}) — "
            f"LKR {self.price_lkr:,} | Stock: {self.stock} | {self.specifications}"
        )


def _clean_int(val: Any, default: int = 0) -> int:
    """Safely parse integer values from CSV fields."""
    if isinstance(val, (int, float)):
        return int(val)
    if not isinstance(val, str):
        return default
    cleaned = re.sub(r"[^\d]", "", val)
    return int(cleaned) if cleaned else default


def load_catalogue(csv_path: Path | str | None = None) -> list[Product]:
    """Load products from the CSV catalogue file into structured records.

    Raises:
        CatalogueFileNotFoundError: If the CSV file does not exist.
        CatalogueDataError: If the CSV file is empty, missing headers, or corrupt.
    """
    path = Path(csv_path) if csv_path is not None else CATALOGUE_CSV_PATH

    if not path.is_file():
        logger.error("Catalogue CSV file not found at path: %s", path)
        raise CatalogueFileNotFoundError(f"Catalogue file not found at: {path}")

    products: list[Product] = []
    required_fields = {
        "product_id",
        "product_name",
        "category",
        "brand",
        "price_lkr",
        "stock",
        "description",
        "specifications",
    }

    try:
        with open(path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CatalogueDataError(f"Catalogue CSV at {path} is empty or has no header row.")

            missing_fields = required_fields - {field.strip() for field in reader.fieldnames if field}
            if missing_fields:
                raise CatalogueDataError(
                    f"Catalogue CSV missing required columns: {sorted(missing_fields)}"
                )

            for row_idx, row in enumerate(reader, start=2):
                if not any(row.values()):
                    continue  # Skip blank lines

                cleaned_row = {
                    (k.strip() if k else ""): (v.strip() if v else "")
                    for k, v in row.items()
                }

                prod_id = cleaned_row.get("product_id", "")
                prod_name = cleaned_row.get("product_name", "")
                if not prod_id or not prod_name:
                    logger.warning("Row %d missing product_id or product_name, skipping", row_idx)
                    continue

                product = Product(
                    product_id=prod_id,
                    product_name=prod_name,
                    category=cleaned_row.get("category", ""),
                    brand=cleaned_row.get("brand", ""),
                    price_lkr=_clean_int(cleaned_row.get("price_lkr")),
                    stock=_clean_int(cleaned_row.get("stock")),
                    description=cleaned_row.get("description", ""),
                    specifications=cleaned_row.get("specifications", ""),
                )
                products.append(product)

    except (csv.Error, UnicodeDecodeError) as err:
        logger.exception("Error decoding catalogue CSV at %s: %s", path, err)
        raise CatalogueDataError(f"Failed to parse CSV file: {err}") from err
    except CatalogueError:
        raise
    except Exception as err:
        logger.exception("Unexpected error reading catalogue CSV: %s", err)
        raise CatalogueDataError(f"Unexpected error loading catalogue: {err}") from err

    if not products:
        logger.warning("Catalogue loaded from %s contains 0 valid products", path)

    return products


# -------------------------------------------------------------------------
# Intent Classification & Search Engine
# -------------------------------------------------------------------------

# Distinctive product patterns ranked by specificity
SPECIFIC_PRODUCT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(r001|basic\s+wifi(\s+router)?|basic\s+router)\b", re.IGNORECASE), "R001"),
    (re.compile(r"\b(r002|dual\s*band(\s+wireless)?(\s+router)?)\b", re.IGNORECASE), "R002"),
    (re.compile(r"\b(r003|fib(?:re|er)(\s+internet)?(\s+router)?)\b", re.IGNORECASE), "R003"),
    (re.compile(r"\b(d001|network\s+switch|8\s*ports?\s+switch|switch)\b", re.IGNORECASE), "D001"),
    (re.compile(r"\b(d002|wifi\s+(?:range\s+)?extender|range\s+extender|extender)\b", re.IGNORECASE), "D002"),
]

# Patterns detecting document, policy, warranty, and manual questions
DOCUMENT_INTENT_PATTERN = re.compile(
    r"\b("
    r"warranty|guarantee|policy|policies|terms|conditions|refund|return|"
    r"replacement|repair|sla|agreement|contract|manual|user\s+guide|"
    r"installation\s+guide|how\s+to\s+install|support\s+policy|pdf|uploaded(\s+document)?"
    r")\b",
    re.IGNORECASE,
)

# Patterns detecting catalogue-related inquiry
CATALOGUE_INTENT_PATTERN = re.compile(
    r"\b("
    r"r00[1-9]|d00[1-9]|router|routers|switch|switches|extender|extenders|"
    r"wifi|fibre|fiber|dual\s*band|gigabit|ethernet|8\s*ports?|"
    r"price|prices|cost|how\s+much|lkr|rupees|rs\.?|"
    r"stock|in\s+stock|available|inventory|catalogue|catalog|products|items|"
    r"spec|specs|specifications|features|under\s+\d+|below\s+\d+|cheaper"
    r")\b",
    re.IGNORECASE,
)

GREETING_PATTERN = re.compile(
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening)|greetings|help|start)\b",
    re.IGNORECASE,
)


def is_catalogue_query(query: str) -> bool:
    """Return True if the text contains keywords or patterns relating to the product catalogue."""
    if not query or not query.strip():
        return False
    return bool(CATALOGUE_INTENT_PATTERN.search(query))


def is_document_query(query: str) -> bool:
    """Return True if the text contains keywords relating to PDF documents/policies."""
    if not query or not query.strip():
        return False
    return bool(DOCUMENT_INTENT_PATTERN.search(query))


def is_greeting(query: str) -> bool:
    """Return True if the message appears to be a greeting without specific question."""
    cleaned = query.strip()
    return bool(GREETING_PATTERN.match(cleaned)) and len(cleaned.split()) <= 4


def _find_specific_product(query: str, products: list[Product]) -> Product | None:
    """Match a query to a specific product record, preferring high-specificity matches."""
    products_by_id = {p.product_id.upper(): p for p in products}

    # 1. Check regex rules with distinctive phrases and IDs
    for pattern, target_id in SPECIFIC_PRODUCT_PATTERNS:
        if pattern.search(query):
            if target_id in products_by_id:
                return products_by_id[target_id]

    # 2. Check direct product ID match
    id_match = re.search(r"\b([a-zA-Z]\d{3})\b", query)
    if id_match:
        pid = id_match.group(1).upper()
        if pid in products_by_id:
            return products_by_id[pid]

    # 3. Check exact/substring product name match
    query_lower = query.lower()
    for product in sorted(products, key=lambda p: len(p.product_name), reverse=True):
        if product.product_name.lower() in query_lower:
            return product

    return None


def _detect_attribute_intent(query: str) -> str:
    """Detect whether user asks specifically for price, stock, or specifications."""
    price_pattern = re.compile(r"\b(price|cost|how\s+much|lkr|rupees|rs\.?|rate|charge|fee)\b", re.IGNORECASE)
    stock_pattern = re.compile(r"\b(stock|how\s+many(\s+are|\s+in)?|quantity|units|how\s+much\s+stock|available\s+count)\b", re.IGNORECASE)
    specs_pattern = re.compile(r"\b(spec|specs|specification|specifications|feature|features|details|tell\s+me\s+about|info)\b", re.IGNORECASE)

    has_price = bool(price_pattern.search(query))
    has_stock = bool(stock_pattern.search(query))
    has_specs = bool(specs_pattern.search(query))

    if has_price and not has_stock:
        return "price"
    if has_stock and not has_price:
        return "stock"
    if has_specs:
        return "specs"
    return "general"


def _format_product_attribute_response(product: Product, intent: str) -> str:
    """Format a response for a specific product depending on the requested attribute."""
    if intent == "price":
        return (
            f"The price of *{product.product_name}* (ID: {product.product_id}) is *LKR {product.price_lkr:,}*.\n\n"
            f"• Stock: {product.stock} units available\n"
            f"• Category: {product.category}\n"
            f"• Specifications: {product.specifications}"
        )
    if intent == "stock":
        if product.stock > 0:
            return (
                f"We currently have *{product.stock} units* of *{product.product_name}* "
                f"(ID: {product.product_id}) in stock.\n\n"
                f"• Price: LKR {product.price_lkr:,}\n"
                f"• Description: {product.description}\n"
                f"• Specifications: {product.specifications}"
            )
        return (
            f"Currently, *{product.product_name}* (ID: {product.product_id}) is *out of stock*.\n\n"
            f"• Price: LKR {product.price_lkr:,}\n"
            f"• Specifications: {product.specifications}"
        )

    # General / specs / tell me about
    return product.format_card()


def _parse_price_filter(query: str) -> tuple[int | None, int | None]:
    """Extract price filter limits (min_price, max_price) from query."""
    under_pattern = re.compile(
        r"\b(?:under|below|less\s+than|cheaper\s+than|maximum|at\s+most|up\s+to)\s+"
        r"(?:lkr\s*|rs\.?\s*|rupees\s*)?([0-9,]+)(?:\s*(?:lkr|rs\.?|rupees))?\b",
        re.IGNORECASE,
    )
    above_pattern = re.compile(
        r"\b(?:above|over|more\s+than|greater\s+than|at\s+least|minimum)\s+"
        r"(?:lkr\s*|rs\.?\s*|rupees\s*)?([0-9,]+)(?:\s*(?:lkr|rs\.?|rupees))?\b",
        re.IGNORECASE,
    )
    between_pattern = re.compile(
        r"\bbetween\s+(?:lkr\s*|rs\.?\s*|rupees\s*)?([0-9,]+)\s+and\s+"
        r"(?:lkr\s*|rs\.?\s*|rupees\s*)?([0-9,]+)(?:\s*(?:lkr|rs\.?|rupees))?\b",
        re.IGNORECASE,
    )

    between_match = between_pattern.search(query)
    if between_match:
        p1 = _clean_int(between_match.group(1))
        p2 = _clean_int(between_match.group(2))
        return min(p1, p2), max(p1, p2)

    max_price = None
    min_price = None

    under_match = under_pattern.search(query)
    if under_match:
        max_price = _clean_int(under_match.group(1))

    above_match = above_pattern.search(query)
    if above_match:
        min_price = _clean_int(above_match.group(1))

    return min_price, max_price


def _filter_by_price(
    products: list[Product],
    min_price: int | None,
    max_price: int | None,
    category_filter: str | None = None,
) -> str:
    """Filter products by price bounds and optional category."""
    matched: list[Product] = []
    for p in products:
        if category_filter and category_filter.lower() not in p.category.lower():
            continue
        if min_price is not None and p.price_lkr < min_price:
            continue
        if max_price is not None and p.price_lkr > max_price:
            continue
        matched.append(p)

    matched.sort(key=lambda p: p.price_lkr)

    # Format header description
    if min_price is not None and max_price is not None:
        criteria = f"between LKR {min_price:,} and LKR {max_price:,}"
    elif max_price is not None:
        criteria = f"under LKR {max_price:,}"
    else:
        criteria = f"above LKR {min_price:,}"

    cat_label = f" ({category_filter.capitalize()}s)" if category_filter else ""

    if not matched:
        cheapest = min(products, key=lambda p: p.price_lkr) if products else None
        cheapest_msg = (
            f" Our lowest priced item is *{cheapest.product_name}* at LKR {cheapest.price_lkr:,}."
            if cheapest
            else ""
        )
        return f"No products found {criteria}{cat_label}.{cheapest_msg}"

    lines = [f"Here are the products found {criteria}{cat_label}:"]
    for idx, p in enumerate(matched, start=1):
        lines.append(
            f"{idx}. *{p.product_name}* ({p.product_id}) — LKR {p.price_lkr:,} (Stock: {p.stock})\n"
            f"   Category: {p.category} | Specs: {p.specifications}"
        )
    return "\n\n".join(lines)


def _handle_category_listing(category_name: str, products: list[Product]) -> str:
    """List products belonging to a particular category."""
    matched = [p for p in products if category_name.lower() in p.category.lower()]
    if not matched:
        return f"No products found in category '{category_name}'."

    matched.sort(key=lambda p: p.price_lkr)
    lines = [f"Available *{category_name.capitalize()}* devices in our catalogue:"]
    for idx, p in enumerate(matched, start=1):
        lines.append(
            f"{idx}. *{p.product_name}* (ID: {p.product_id}) — LKR {p.price_lkr:,}\n"
            f"   • Stock: {p.stock} units | Specs: {p.specifications}\n"
            f"   • Description: {p.description}"
        )
    lines.append(
        "Reply with a product name or ID (e.g., 'Price of Fibre Router' or 'Tell me about R002') for more details."
    )
    return "\n\n".join(lines)


def _list_full_catalogue(products: list[Product]) -> str:
    """Format full catalogue overview grouped by category."""
    if not products:
        return "The product catalogue is currently empty."

    categories: dict[str, list[Product]] = {}
    for p in products:
        categories.setdefault(p.category, []).append(p)

    lines = ["📦 *Product Catalogue:*\n"]
    for cat, items in categories.items():
        lines.append(f"*{cat}s:*")
        for p in items:
            lines.append(
                f"• *{p.product_name}* ({p.product_id}) — LKR {p.price_lkr:,} (Stock: {p.stock})"
            )
        lines.append("")

    lines.append("You can ask for specific prices, stock availability, specifications, or filter by price (e.g., 'products under 7000').")
    return "\n".join(lines).strip()


def search_catalogue(query: str, csv_path: Path | str | None = None) -> str:
    """Search the product catalogue based on a user query string.

    Never invents products, prices, or stock quantities.
    Returns a WhatsApp-formatted answer string.
    """
    if not query or not query.strip():
        return (
            "Please provide a product name, ID (e.g., R001), category (e.g., routers), "
            "or price range to search the catalogue."
        )

    try:
        products = load_catalogue(csv_path)
    except CatalogueFileNotFoundError as err:
        logger.error("Catalogue file missing: %s", err)
        return "The product catalogue is currently unavailable (catalogue file not found)."
    except CatalogueDataError as err:
        logger.error("Catalogue data error: %s", err)
        return "The product catalogue is currently unavailable due to a data format issue."
    except Exception as err:
        logger.exception("Unexpected error in search_catalogue: %s", err)
        return "An error occurred while accessing the product catalogue. Please try again later."

    if not products:
        return "The product catalogue is currently empty."

    query_clean = query.strip()
    query_lower = query_clean.lower()

    # 1. Check for specific product match first (highest specificity)
    matched_product = _find_specific_product(query_clean, products)
    if matched_product:
        attribute_intent = _detect_attribute_intent(query_clean)
        return _format_product_attribute_response(matched_product, attribute_intent)

    # 2. Check for price filter queries ("under 7000 rupees", "between 5000 and 10000")
    min_price, max_price = _parse_price_filter(query_clean)
    if min_price is not None or max_price is not None:
        # Check if category is also constrained
        category_filter = None
        if "router" in query_lower:
            category_filter = "Router"
        elif "network" in query_lower or "switch" in query_lower:
            category_filter = "Networking"
        return _filter_by_price(products, min_price, max_price, category_filter)

    # 3. Check for Category listing queries (e.g., "What routers are available?")
    if re.search(r"\b(router|routers)\b", query_lower):
        return _handle_category_listing("Router", products)

    if re.search(r"\b(networking|network\s+devices?)\b", query_lower):
        return _handle_category_listing("Networking", products)

    # 4. Check for full catalogue listing requests
    if re.search(r"\b(all\s+products|catalogue|catalog|what\s+do\s+you\s+have|list\s+products|show\s+products)\b", query_lower):
        return _list_full_catalogue(products)

    # 5. Full-text search across specifications, descriptions, brands
    tokens = [t for t in re.split(r"\W+", query_lower) if len(t) >= 3 and t not in {"the", "and", "for", "with", "you", "have"}]
    if tokens:
        keyword_matches: list[Product] = []
        for p in products:
            searchable_text = f"{p.product_name} {p.category} {p.brand} {p.description} {p.specifications}".lower()
            if any(token in searchable_text for token in tokens):
                keyword_matches.append(p)

        if len(keyword_matches) == 1:
            return keyword_matches[0].format_card()
        if len(keyword_matches) > 1:
            lines = ["Here are matching products from our catalogue:"]
            for idx, p in enumerate(keyword_matches, start=1):
                lines.append(f"{idx}. {p.format_summary_line()}")
            return "\n\n".join(lines)

    # 6. Not found - Grounded response stating available items without inventing anything
    return (
        f"I could not find any products matching '{query_clean}' in our catalogue.\n\n"
        "We currently offer:\n"
        "• *Routers*: Basic WiFi Router (R001), Dual Band Router (R002), Fibre Router (R003)\n"
        "• *Networking*: Network Switch (D001), WiFi Range Extender (D002)\n\n"
        "Please ask about any of these items, check prices/stock, or ask for products by price range."
    )
