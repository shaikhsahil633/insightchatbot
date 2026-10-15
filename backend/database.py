"""
Database connection and schema introspection utilities.
Provides PostgreSQL connectivity and schema metadata for LLM context.
"""
import psycopg2
import psycopg2.extras
from typing import Any
from config import settings


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
    )


def get_schema_description() -> str:
    """
    Generate a compact, LLM-friendly schema description for allowed tables.
    This is injected into the system prompt so the LLM knows the database structure.
    """
    conn = get_connection()
    cur = conn.cursor()
    schema_parts = []

    for table in settings.ALLOWED_TABLES:
        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
        """, (table,))
        columns = cur.fetchall()

        if not columns:
            continue

        col_descriptions = []
        for col_name, data_type, nullable in columns:
            null_str = "" if nullable == "YES" else " NOT NULL"
            col_descriptions.append(f"    {col_name} ({data_type}{null_str})")

        # Get row count for context
        cur.execute(f'SELECT COUNT(*) FROM "{table}";')
        row_count = cur.fetchone()[0]

        schema_parts.append(
            f"TABLE: {table} ({row_count:,} rows)\n" + "\n".join(col_descriptions)
        )

    cur.close()
    conn.close()
    return "\n\n".join(schema_parts)


def get_sample_values(table: str, column: str, limit: int = 10) -> list:
    """Get distinct sample values from a column for LLM context."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT %s;',
            (limit,)
        )
        values = [row[0] for row in cur.fetchall()]
        return values
    except Exception:
        return []
    finally:
        cur.close()
        conn.close()


def execute_safe_query(sql: str) -> dict:
    """
    Execute a validated SELECT query safely.
    Returns structured result with columns and rows.
    """
    # Security: only allow SELECT statements
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed.", "columns": [], "rows": []}

    # Block dangerous keywords
    dangerous = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"]
    for keyword in dangerous:
        if keyword in sql_upper:
            return {"error": f"Forbidden keyword: {keyword}", "columns": [], "rows": []}

    # Enforce LIMIT if not present
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";") + f" LIMIT {settings.MAX_QUERY_ROWS};"

    conn = get_connection()
    cur = conn.cursor()
    try:
        # Set query timeout
        cur.execute(f"SET statement_timeout = '{settings.QUERY_TIMEOUT_SECONDS}s';")
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        # Convert to serializable format
        serialized_rows = []
        for row in rows:
            serialized_row = []
            for val in row:
                if val is None:
                    serialized_row.append(None)
                else:
                    serialized_row.append(str(val))
            serialized_rows.append(serialized_row)

        return {
            "columns": columns,
            "rows": serialized_rows,
            "row_count": len(serialized_rows),
            "sql": sql
        }
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": []}
    finally:
        cur.close()
        conn.close()


def get_table_relationships() -> str:
    """Describe key relationships between tables for LLM context."""
    return """
TABLE RELATIONSHIPS:
- main_1.ean_number links to category_mapping.ean_number (product master data lookup)
- main_1 contains per-retailer, per-date product pricing records
- category_mapping enriches products with ef_category, ef_sub_category, ef_brand, brand_owner
- pivot_unit / pivot_unit_1 contain cross-retailer price comparison matrices (one row per EAN+date, columns per retailer)
- measure_unit / measure_unit_1 contain cross-retailer measure price comparison matrices
- new_measure / pivot are normalized versions (retailer, date, ean_number, price/measure)

KEY BUSINESS CONCEPTS:
- Retailers: Bilka, Føtex, Meny, Netto, Rema, SPAR Glostrup, SPAR Risskov, Min Købmand Rødovre, Min Købmand Søstjernen
- unit_price: numeric price per unit
- discounted_price: promotional/sale price
- offer_description: promotional offer text (default: 'No Promotion Available')
- categories_lvl0 → lvl3: hierarchical product category (e.g., Frugt og grønt > Grøntsager > Gulerødder)
- ean_number: product barcode identifier
- Data date range: April 2025 to March 2026 (Danish market)
"""


def get_business_glossary() -> str:
    """Return business glossary for LLM context."""
    return """
BUSINESS GLOSSARY:
- EAN: European Article Number (product barcode)
- SKU: Stock Keeping Unit
- Unit Price: Price per single unit of the product
- Discounted Price: Sale/promotional price
- Measure Price: Price per unit of measure (e.g., per kg, per liter)
- In Stock: Whether product is currently available
- Multi Promo: Whether product has multiple concurrent promotions
- Categories LVL0-3: Hierarchical product categories (0=broadest, 3=most specific)
- Brand Owner: Parent company owning the brand
- Bilka Avisen: Weekly flyer/advertisement inclusion flag
- Skarp Pris: "Sharp price" / competitive pricing flag
- Retailer names are Danish grocery chains
"""
