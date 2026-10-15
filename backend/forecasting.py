"""
Predictive Price Forecasting Module.
Provides statistical price prediction for products using historical data.
Supports: weighted moving average, linear regression, and category-based context.
"""
import re
import math
from datetime import datetime, timedelta
from typing import Optional
from database import get_connection
from config import settings


def _fetch_product_history(ean: str) -> dict:
    """
    Fetch all historical price data for a product from main_1.
    Returns structured history with product metadata.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Get price history ordered by date
        cur.execute("""
            SELECT date, retailer, unit_price, discounted_price, name
            FROM main_1
            WHERE ean_number = %s
              AND unit_price IS NOT NULL
            ORDER BY date ASC;
        """, (ean,))
        rows = cur.fetchall()

        if not rows:
            return {"found": False, "ean": ean, "data": [], "product_name": None}

        product_name = rows[0][4] if rows[0][4] else f"Product {ean}"

        data = []
        for row in rows:
            data.append({
                "date": row[0],
                "retailer": row[1],
                "unit_price": float(row[2]) if row[2] else None,
                "discounted_price": float(row[3]) if row[3] else None,
            })

        return {
            "found": True,
            "ean": ean,
            "product_name": product_name,
            "data": data,
        }
    finally:
        cur.close()
        conn.close()


def _fetch_category_context(ean: str) -> dict:
    """
    Fetch pricing context for similar products in the same category.
    Useful for market-level trend analysis.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Get the product's category first
        cur.execute("""
            SELECT ef_category, ef_sub_category, ef_brand
            FROM category_mapping
            WHERE ean_number = %s
            LIMIT 1;
        """, (ean,))
        cat_row = cur.fetchone()

        if not cat_row or not cat_row[0]:
            return {"has_context": False}

        category = cat_row[0]
        sub_category = cat_row[1]
        brand = cat_row[2]

        # Get average price trend for the category over time
        cur.execute("""
            SELECT m.date,
                   AVG(m.unit_price) AS avg_price,
                   COUNT(DISTINCT m.ean_number) AS product_count
            FROM main_1 m
            JOIN category_mapping c ON m.ean_number = c.ean_number
            WHERE c.ef_category = %s
              AND m.unit_price IS NOT NULL
            GROUP BY m.date
            ORDER BY m.date ASC;
        """, (category,))
        cat_trend = cur.fetchall()

        category_data = []
        for row in cat_trend:
            category_data.append({
                "date": row[0],
                "avg_price": float(row[1]),
                "product_count": row[2],
            })

        return {
            "has_context": True,
            "category": category,
            "sub_category": sub_category,
            "brand": brand,
            "category_trend": category_data,
        }
    except Exception:
        return {"has_context": False}
    finally:
        cur.close()
        conn.close()


def _linear_regression(x_vals: list, y_vals: list) -> tuple:
    """
    Simple linear regression: y = mx + b.
    Returns (slope, intercept, r_squared).
    Uses pure Python — no numpy required.
    """
    n = len(x_vals)
    if n < 2:
        return (0.0, y_vals[0] if y_vals else 0.0, 0.0)

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x * x for x in x_vals)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return (0.0, sum_y / n, 0.0)

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    # R-squared calculation
    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return (slope, intercept, r_squared)


def _weighted_moving_average(prices: list, weights: list = None) -> float:
    """
    Compute weighted moving average with more weight on recent prices.
    """
    n = len(prices)
    if n == 0:
        return 0.0
    if n == 1:
        return prices[0]

    if weights is None:
        # Exponentially increasing weights (recent = heavier)
        weights = [2 ** i for i in range(n)]

    total_weight = sum(weights)
    wma = sum(p * w for p, w in zip(prices, weights)) / total_weight
    return wma


def _calculate_volatility(prices: list) -> float:
    """
    Calculate the coefficient of variation (CV) of prices as a volatility measure.
    CV = std_dev / mean * 100
    """
    if len(prices) < 2:
        return 0.0

    mean = sum(prices) / len(prices)
    if mean == 0:
        return 0.0

    variance = sum((p - mean) ** 2 for p in prices) / (len(prices) - 1)
    std_dev = math.sqrt(variance)
    return (std_dev / mean) * 100


def forecast_product_price(ean: str, months_ahead: int = 1) -> dict:
    """
    Main forecasting function. Predicts future price for a given product.

    Strategy:
    - If price is completely stable → predict same price, high confidence
    - If enough data points → use linear regression for trend projection
    - Always enhance with weighted moving average
    - Provide category context for market-level insights

    Returns a structured forecast result for LLM summarization.
    """
    # Fetch historical data
    history = _fetch_product_history(ean)

    if not history["found"]:
        return {
            "success": False,
            "ean": ean,
            "error": "no_data",
            "message": f"No historical price data found for EAN {ean}. "
                       "This product may not exist in the database or may have never been tracked.",
        }

    data = history["data"]
    product_name = history["product_name"]

    # Group prices by date (average across retailers if multiple)
    date_prices = {}
    retailers = set()
    for d in data:
        date_key = d["date"]
        retailers.add(d["retailer"])
        if date_key not in date_prices:
            date_prices[date_key] = []
        date_prices[date_key].append(d["unit_price"])

    # Compute daily average prices (sorted by date)
    sorted_dates = sorted(date_prices.keys())
    avg_prices = [sum(date_prices[d]) / len(date_prices[d]) for d in sorted_dates]

    n_points = len(avg_prices)
    latest_price = avg_prices[-1]
    latest_date = sorted_dates[-1]
    earliest_date = sorted_dates[0]

    # Calculate prediction target date
    target_date = latest_date + timedelta(days=30 * months_ahead)

    # ── Volatility analysis ──
    volatility = _calculate_volatility(avg_prices)
    is_stable = volatility < 1.0  # < 1% CV = very stable

    # ── Prediction strategy ──
    if is_stable or n_points < 3:
        # Stable price or too few data points for regression
        predicted_price = latest_price
        method = "stable_price"
        confidence = "high" if is_stable and n_points >= 3 else "moderate"
        confidence_pct = 92 if is_stable and n_points >= 3 else 70

        trend_direction = "stable"
        trend_description = (
            f"The price has remained completely stable at {latest_price:.2f} DKK "
            f"across {n_points} observations from {earliest_date} to {latest_date}."
        )
    else:
        # Enough data for regression-based prediction
        # Convert dates to numeric (days since first observation)
        x_vals = [(d - earliest_date).days for d in sorted_dates]
        slope, intercept, r_squared = _linear_regression(x_vals, avg_prices)

        # Project to target date
        target_x = (target_date - earliest_date).days
        regression_prediction = slope * target_x + intercept

        # Weighted moving average prediction
        wma_prediction = _weighted_moving_average(avg_prices)

        # Blend: weight regression more if R² is high
        if r_squared > 0.7:
            predicted_price = 0.7 * regression_prediction + 0.3 * wma_prediction
            confidence = "high"
            confidence_pct = int(75 + r_squared * 20)
        elif r_squared > 0.4:
            predicted_price = 0.5 * regression_prediction + 0.5 * wma_prediction
            confidence = "moderate"
            confidence_pct = int(55 + r_squared * 25)
        else:
            predicted_price = 0.3 * regression_prediction + 0.7 * wma_prediction
            confidence = "low"
            confidence_pct = int(40 + r_squared * 20)

        # Ensure price doesn't go negative
        predicted_price = max(predicted_price, 0.01)

        # Determine trend
        price_change = predicted_price - latest_price
        pct_change = (price_change / latest_price) * 100 if latest_price > 0 else 0

        if pct_change > 2:
            trend_direction = "increasing"
        elif pct_change < -2:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"

        method = "regression_wma_blend"
        trend_description = (
            f"Based on {n_points} data points from {earliest_date} to {latest_date}, "
            f"linear regression (R²={r_squared:.3f}) shows a "
            f"{'positive' if slope > 0 else 'negative' if slope < 0 else 'flat'} trend "
            f"of {slope:.4f} DKK/day. "
            f"Predicted change: {pct_change:+.2f}%."
        )

    # ── Category context ──
    category_context = _fetch_category_context(ean)

    category_summary = None
    if category_context.get("has_context") and category_context.get("category_trend"):
        cat_trend = category_context["category_trend"]
        if len(cat_trend) >= 2:
            first_avg = cat_trend[0]["avg_price"]
            last_avg = cat_trend[-1]["avg_price"]
            cat_change = ((last_avg - first_avg) / first_avg) * 100 if first_avg > 0 else 0
            category_summary = (
                f"Category '{category_context['category']}' "
                f"(sub: {category_context.get('sub_category', 'N/A')}) "
                f"has seen an overall price change of {cat_change:+.2f}% "
                f"across {cat_trend[-1].get('product_count', 'N/A')} tracked products."
            )

    # ── Build result ──
    # Historical summary for the LLM
    price_history_summary = []
    for date, price in zip(sorted_dates, avg_prices):
        price_history_summary.append(f"  {date}: {price:.2f} DKK")

    return {
        "success": True,
        "ean": ean,
        "product_name": product_name,
        "retailers": list(retailers),
        "prediction": {
            "target_date": str(target_date),
            "months_ahead": months_ahead,
            "predicted_price": round(predicted_price, 2),
            "confidence": confidence,
            "confidence_pct": confidence_pct,
            "trend_direction": trend_direction,
            "method": method,
        },
        "historical": {
            "data_points": n_points,
            "date_range": f"{earliest_date} to {latest_date}",
            "latest_price": round(latest_price, 2),
            "min_price": round(min(avg_prices), 2),
            "max_price": round(max(avg_prices), 2),
            "avg_price": round(sum(avg_prices) / n_points, 2),
            "volatility_pct": round(volatility, 2),
            "price_timeline": price_history_summary,
        },
        "trend_description": trend_description,
        "category_context": category_summary,
    }


def extract_ean_from_question(question: str) -> Optional[str]:
    """
    Extract an EAN number from a user's question.
    EANs are typically 8-13 digit numbers.
    """
    # Look for numeric strings that could be EANs (8-13 digits)
    matches = re.findall(r'\b(\d{8,13})\b', question)
    if matches:
        return matches[0]
    return None


def extract_months_ahead(question: str) -> int:
    """
    Extract how many months ahead to predict from the question.
    Default: 1 month.
    """
    q_lower = question.lower()

    # Explicit month numbers
    month_match = re.search(r'(\d+)\s*months?\s*(ahead|from now|later|forward)', q_lower)
    if month_match:
        return min(int(month_match.group(1)), 12)  # Cap at 12 months

    # Named time periods
    if any(w in q_lower for w in ["next quarter", "3 months"]):
        return 3
    if any(w in q_lower for w in ["next half", "6 months"]):
        return 6
    if any(w in q_lower for w in ["next year", "12 months"]):
        return 12
    if any(w in q_lower for w in ["next 2 months", "two months"]):
        return 2

    # Default: next month
    return 1


def build_forecast_summary_for_llm(forecast: dict) -> str:
    """
    Build a structured text summary of the forecast result
    for the LLM to use in generating the final user-facing response.
    """
    if not forecast["success"]:
        return f"FORECAST FAILED: {forecast['message']}"

    pred = forecast["prediction"]
    hist = forecast["historical"]

    lines = [
        f"PRODUCT PRICE FORECAST",
        f"Product: {forecast['product_name']} (EAN: {forecast['ean']})",
        f"Retailers: {', '.join(forecast['retailers'])}",
        f"",
        f"PREDICTION:",
        f"  Target Date: {pred['target_date']}",
        f"  Predicted Price: {pred['predicted_price']:.2f} DKK",
        f"  Confidence: {pred['confidence']} ({pred['confidence_pct']}%)",
        f"  Trend Direction: {pred['trend_direction']}",
        f"  Method: {pred['method']}",
        f"",
        f"HISTORICAL DATA:",
        f"  Data Points: {hist['data_points']}",
        f"  Date Range: {hist['date_range']}",
        f"  Latest Price: {hist['latest_price']:.2f} DKK",
        f"  Price Range: {hist['min_price']:.2f} – {hist['max_price']:.2f} DKK",
        f"  Average Price: {hist['avg_price']:.2f} DKK",
        f"  Volatility: {hist['volatility_pct']:.2f}%",
        f"",
        f"PRICE TIMELINE:",
    ]
    lines.extend(hist["price_timeline"])

    lines.append(f"")
    lines.append(f"TREND ANALYSIS: {forecast['trend_description']}")

    if forecast.get("category_context"):
        lines.append(f"")
        lines.append(f"CATEGORY CONTEXT: {forecast['category_context']}")

    return "\n".join(lines)
