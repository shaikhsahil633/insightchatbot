"""
Chat engine — the core NL-to-SQL pipeline.
Orchestrates: user question → LLM (SQL generation) → DB execution → LLM (summarization) → response.
Also handles predictive forecasting via the forecasting module.
"""
import json
import re
from typing import Optional
from llm_provider import get_llm_provider, extract_sql_from_response
from database import (
    get_schema_description,
    get_table_relationships,
    get_business_glossary,
    execute_safe_query,
)
from forecasting import (
    forecast_product_price,
    extract_ean_from_question,
    extract_months_ahead,
    build_forecast_summary_for_llm,
)


# Cache the schema description (it doesn't change at runtime)
_cached_schema: Optional[str] = None


def get_cached_schema() -> str:
    """Get the schema description, cached after first call."""
    global _cached_schema
    if _cached_schema is None:
        _cached_schema = get_schema_description()
    return _cached_schema


def build_sql_generation_prompt() -> str:
    """Build the system prompt for SQL generation."""
    schema = get_cached_schema()
    relationships = get_table_relationships()
    glossary = get_business_glossary()

    return f"""You are a PostgreSQL expert working with a Danish grocery retail price monitoring database called "Effect Manager".

Your task: Given a user question, generate a valid PostgreSQL SELECT query to answer it.

STRICT RULES:
1. ONLY output a valid SELECT query — nothing else. No explanation, no markdown, no commentary.
2. NEVER use DROP, DELETE, UPDATE, INSERT, TRUNCATE, ALTER, CREATE, GRANT, or REVOKE.
3. Always include LIMIT 500 unless the user explicitly specifies a different limit.
4. Use double quotes around column/table names that contain special characters or spaces.
5. For text comparisons, use ILIKE for case-insensitive matching.
6. When the user asks about "price", they typically mean unit_price from pivot_unit or main_1.
7. IMPORTANT CATEGORY MAPPING: The categories are in Danish. If a user asks for "dairy", search `ef_category ILIKE '%mejeri%'` in `category_mapping`. For "fruits/vegetables", use `'%frugt%'` or `'%grønt%'`. For "meat", use `'%kød%'`. For "beverages", use `'%drikke%'`.
8. Always handle NULLs appropriately with COALESCE or IS NOT NULL filters.
9. DATE FILTERING: The data ranges from April 2025 to April 2026. If the user asks for "the last 3 months", use `date >= '2026-01-01'`. Do NOT use `CURRENT_DATE` as the system date might be out of sync with the dataset. Use explicit dates in 2026.
10. Output ONLY the SQL query — no wrapping in code blocks, no JSON, just raw SQL.

{relationships}

{glossary}

DATABASE SCHEMA:
{schema}

Remember: Output ONLY the raw SQL SELECT query. Nothing else."""


def build_summary_prompt() -> str:
    """Build the system prompt for summarizing query results."""
    return """You are an expert predictive data analyst and business strategist for a Danish grocery retail price monitoring system.

Given a user question, the SQL query that was executed, and the query results, provide a comprehensive analysis:

1. **Direct Answer**: Provide a clear, concise natural language answer to the user's question.
2. **Deep Insights & Anomalies**: Highlight key patterns, unexpected anomalies, or hidden trends in the data. Look for things a standard report might miss.
3. **Predictive Forecasting & Business Impact**: If the data shows a trend (especially time-series or comparative data), provide a brief, logical prediction or hypothesis about future movements. Explain what this means for business strategy or pricing competitiveness.
4. **Actionable Next Steps**: Suggest 1-2 strategic actions or follow-up analytical questions based on these insights.

RULES:
- Be specific with numbers and percentages — don't round excessively.
- Format numbers with appropriate units (e.g., DKK for prices).
- Use bolding and bullet points strategically to make the analysis highly readable.
- If the result set is empty or insufficient for predictions, explain what that likely means and what data would be needed.
- Keep your response under 350 words, dense with value.
- Do NOT output any SQL or code.
- Respond in English even though the data contains Danish text."""


def build_forecast_prompt() -> str:
    """Build the system prompt for summarizing forecast/prediction results."""
    return """You are an expert predictive data analyst and business strategist for a Danish grocery retail price monitoring system.

You have been given the results of a STATISTICAL PRICE FORECAST for a specific product. Your job is to present these findings in a clear, insightful, and actionable format.

Provide your response in this structure:

1. **Price Prediction**: State the predicted price clearly with the target date and confidence level. Explain in plain language what this means.
2. **Historical Analysis**: Summarize the price history — trend, stability, and any notable patterns.
3. **Methodology**: Briefly explain how the prediction was calculated (statistical method used, data points analyzed).
4. **Market Context**: If category-level data is provided, relate the product's trend to the broader market.
5. **Business Recommendations**: Provide 2-3 actionable insights for pricing strategy, procurement, or competitive positioning.

RULES:
- Present the predicted price prominently with currency (DKK).
- Include the confidence level and explain what it means practically.
- Be specific with numbers — don't round excessively.
- Use bolding and bullet points for readability.
- If the confidence is low, emphasize that this is an estimate and recommend monitoring.
- Keep your response under 400 words, dense with value.
- Do NOT output any SQL, code, or raw data dumps.
- Respond in English even though the data contains Danish text."""


def determine_chart_type(columns: list, rows: list, question: str) -> Optional[dict]:
    """
    Heuristic chart type detection based on query results.
    Returns chart configuration or None if no chart is appropriate.
    """
    if not columns or not rows or len(rows) < 2:
        return None

    question_lower = question.lower()
    num_columns = len(columns)

    # Detect date/time columns
    has_date = any("date" in col.lower() for col in columns)

    # Detect numeric columns (check first row)
    all_numeric_cols = []
    text_cols = []
    for i, col in enumerate(columns):
        if rows[0][i] is not None:
            try:
                float(rows[0][i])
                all_numeric_cols.append(col)
            except (ValueError, TypeError):
                text_cols.append(col)
        else:
            text_cols.append(col)

    if not all_numeric_cols:
        return None

    # Filter out IDs from numeric columns for the Y-axis priority
    metric_cols = [c for c in all_numeric_cols if "ean" not in c.lower() and "id" not in c.lower() and "code" not in c.lower()]
    
    # Priority 1: Columns that explicitly sound like metrics
    priority_metrics = [c for c in metric_cols if any(k in c.lower() for k in ["price", "amount", "count", "avg", "sum", "max", "min"])]
    
    # Determine the best Y-axis column
    if priority_metrics:
        y_col = priority_metrics[0]
    elif metric_cols:
        y_col = metric_cols[0]
    else:
        y_col = all_numeric_cols[0] # Fallback to IDs if nothing else exists

    # Time series: date column + numeric column → line chart
    if has_date:
        date_col = next(col for col in columns if "date" in col.lower())
        return {
            "type": "line",
            "x": date_col,
            "y": y_col,
            "title": f"{y_col} over time",
        }

    # Comparison queries → bar chart
    if (
        "compare" in question_lower
        or "top" in question_lower
        or "highest" in question_lower
        or "lowest" in question_lower
        or "most" in question_lower
    ):
        if text_cols:
            return {
                "type": "bar",
                "x": text_cols[0],
                "y": y_col,
                "title": f"{y_col} by {text_cols[0]}",
            }

    # Distribution / proportion → pie chart
    if "distribution" in question_lower or "proportion" in question_lower or "share" in question_lower:
        if text_cols:
            return {
                "type": "pie",
                "nameKey": text_cols[0],
                "dataKey": y_col,
                "title": f"Distribution of {y_col}",
            }

    # Category + numeric → bar chart (default for grouped data)
    if text_cols and len(rows) <= 30:
        return {
            "type": "bar",
            "x": text_cols[0],
            "y": y_col,
            "title": f"{y_col} by {text_cols[0]}",
        }

    return None


async def process_question(question: str, conversation_history: list = None) -> dict:
    """
    Main pipeline: process a natural language question and return structured response.

    Returns:
        {
            "answer": str,          # Natural language answer
            "sql": str|None,        # Generated SQL query
            "data": dict|None,      # Query results {columns, rows, row_count}
            "chart": dict|None,     # Chart configuration
            "error": str|None,      # Error message if any
        }
    """
    llm = get_llm_provider()

    # Step 1: Classify intent — is this a data question or conversational?
    if _is_conversational(question):
        return {
            "answer": await _handle_conversational(question, llm),
            "sql": None,
            "data": None,
            "chart": None,
            "error": None,
        }

    # Step 1b: Check if this is a predictive/forecasting question
    if _is_predictive(question):
        return await _handle_prediction(question, llm)

    # Step 2: Generate SQL from the question
    sql_prompt = build_sql_generation_prompt()

    # Include conversation context if available
    context = ""
    if conversation_history and len(conversation_history) > 0:
        recent = conversation_history[-3:]  # Last 3 turns
        context = "Previous conversation context:\n"
        for turn in recent:
            context += f"User: {turn.get('question', '')}\n"
            if turn.get('sql'):
                context += f"SQL used: {turn['sql']}\n"
        context += "\nCurrent question: "

    try:
        sql_response = await llm.generate(sql_prompt, context + question)
    except Exception as e:
        return {
            "answer": f"I'm having trouble connecting to the AI model. Please make sure Ollama is running. Error: {str(e)}",
            "sql": None,
            "data": None,
            "chart": None,
            "error": str(e),
        }

    # Step 3: Extract SQL from LLM response
    sql = extract_sql_from_response(sql_response)
    if not sql:
        return {
            "answer": "I couldn't generate a valid SQL query for your question. Could you please rephrase it or be more specific about what data you're looking for?",
            "sql": None,
            "data": None,
            "chart": None,
            "error": "Failed to extract SQL from LLM response",
        }

    # Step 4: Execute the SQL safely
    result = execute_safe_query(sql)
    if "error" in result and result["error"]:
        # Try once more with error feedback
        retry_prompt = f"""The previous SQL query failed with error: {result['error']}

Original question: {question}
Failed SQL: {sql}

Please generate a corrected SQL query. Output ONLY the raw SQL, nothing else."""

        try:
            retry_response = await llm.generate(sql_prompt, retry_prompt)
            sql = extract_sql_from_response(retry_response) or sql
            result = execute_safe_query(sql)
        except Exception:
            pass

        if "error" in result and result["error"]:
            return {
                "answer": f"I generated a query but it encountered an error: {result['error']}. Please try rephrasing your question.",
                "sql": sql,
                "data": None,
                "chart": None,
                "error": result["error"],
            }

    # Step 5: Summarize results with LLM
    summary_prompt = build_summary_prompt()

    # Prepare result summary for LLM (truncate if too large)
    rows_for_summary = result["rows"][:50]  # Max 50 rows for summary
    result_text = f"""User Question: {question}

SQL Query Executed:
{sql}

Query Results ({result['row_count']} rows returned):
Columns: {', '.join(result['columns'])}

Data:
"""
    for row in rows_for_summary:
        result_text += " | ".join(str(v) for v in row) + "\n"

    if result["row_count"] > 50:
        result_text += f"\n... and {result['row_count'] - 50} more rows"

    try:
        answer = await llm.generate(summary_prompt, result_text)
    except Exception:
        # Fallback: provide raw data description
        answer = f"Query returned {result['row_count']} rows across {len(result['columns'])} columns: {', '.join(result['columns'])}."

    # Step 6: Determine chart type
    chart_config = determine_chart_type(result["columns"], result["rows"], question)

    return {
        "answer": answer,
        "sql": sql,
        "data": {
            "columns": result["columns"],
            "rows": result["rows"][:200],  # Cap at 200 rows for frontend
            "row_count": result["row_count"],
        },
        "chart": chart_config,
        "error": None,
    }


def _is_predictive(question: str) -> bool:
    """
    Check if the question is asking for a price prediction/forecast.
    Matches patterns like: 'next month price', 'predict price', 'forecast', etc.
    Also triggers when an EAN is present and the question implies future pricing.
    """
    q_lower = question.strip().lower()

    # Direct prediction keywords
    prediction_keywords = [
        r"\bnext\s+month\b",
        r"\bnext\s+\d+\s+months?\b",
        r"\bpredict\b",
        r"\bprediction\b",
        r"\bforecast\b",
        r"\bforecasting\b",
        r"\bfuture\s+price\b",
        r"\bprice\s+prediction\b",
        r"\bprice\s+forecast\b",
        r"\bexpected\s+price\b",
        r"\bestimate\s+price\b",
        r"\bprice\s+estimate\b",
        r"\bwill\s+(the\s+)?price\b",
        r"\bprice\s+in\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        r"\bprice\s+next\b",
        r"\bupcoming\s+(month|price)\b",
        r"\bprojected\s+price\b",
        r"\bprice\s+projection\b",
        r"\bprice\s+trend\s+predict\b",
        r"\bnext\s+month\s+price\b",
    ]

    for pattern in prediction_keywords:
        if re.search(pattern, q_lower):
            return True

    # If question has an EAN and words implying future
    has_ean = bool(re.search(r'\b\d{8,13}\b', q_lower))
    has_future_word = any(w in q_lower for w in [
        "next", "future", "predict", "forecast", "will",
        "upcoming", "expected", "estimate", "projection",
    ])
    if has_ean and has_future_word:
        return True

    return False


async def _handle_prediction(question: str, llm) -> dict:
    """
    Handle a predictive question by running statistical forecasting
    and summarizing the results with the LLM.
    """
    # Extract EAN from question
    ean = extract_ean_from_question(question)
    if not ean:
        return {
            "answer": (
                "I'd love to predict a price for you, but I couldn't identify a product EAN number in your question. "
                "Please include the EAN (barcode number, typically 8-13 digits) of the product you want a forecast for.\n\n"
                "**Example**: *Predict the next month price for 3558270002448*"
            ),
            "sql": None,
            "data": None,
            "chart": None,
            "error": None,
        }

    # Determine prediction horizon
    months_ahead = extract_months_ahead(question)

    # Run the forecast
    forecast = forecast_product_price(ean, months_ahead)

    if not forecast["success"]:
        return {
            "answer": forecast["message"],
            "sql": None,
            "data": None,
            "chart": None,
            "error": forecast.get("error"),
        }

    # Build the forecast summary text for LLM
    forecast_text = build_forecast_summary_for_llm(forecast)
    llm_input = f"User Question: {question}\n\n{forecast_text}"

    # Get LLM to write a polished, insightful response
    forecast_prompt = build_forecast_prompt()
    try:
        answer = await llm.generate(forecast_prompt, llm_input)
    except Exception:
        # Fallback: return the raw forecast data in a readable format
        pred = forecast["prediction"]
        hist = forecast["historical"]
        answer = (
            f"**Price Prediction for {forecast['product_name']}** (EAN: {ean})\n\n"
            f"📈 **Predicted Price**: {pred['predicted_price']:.2f} DKK "
            f"(by {pred['target_date']})\n"
            f"🎯 **Confidence**: {pred['confidence']} ({pred['confidence_pct']}%)\n"
            f"📊 **Trend**: {pred['trend_direction']}\n\n"
            f"**Historical Context**: {hist['data_points']} data points from {hist['date_range']}. "
            f"Latest price: {hist['latest_price']:.2f} DKK. "
            f"Volatility: {hist['volatility_pct']:.2f}%.\n\n"
            f"{forecast['trend_description']}"
        )

    # Build chart data from historical prices
    chart_data = None
    hist = forecast["historical"]
    if hist["data_points"] >= 2:
        # Parse the price timeline for chart
        chart_rows = []
        for entry in hist["price_timeline"]:
            # Format: "  2026-02-15: 282.58 DKK"
            parts = entry.strip().split(": ")
            if len(parts) == 2:
                chart_rows.append([parts[0], parts[1].replace(" DKK", "")])

        # Add the prediction point
        pred = forecast["prediction"]
        chart_rows.append([pred["target_date"], str(pred["predicted_price"])])

        chart_data = {
            "columns": ["date", "price_dkk"],
            "rows": chart_rows,
            "row_count": len(chart_rows),
        }

    # Build chart config
    chart_config = {
        "type": "line",
        "x": "date",
        "y": "price_dkk",
        "title": f"Price Forecast: {forecast['product_name']}",
    } if chart_data else None

    return {
        "answer": answer,
        "sql": f"-- Statistical forecast (not SQL-based)\n-- Method: {forecast['prediction']['method']}\n-- Confidence: {forecast['prediction']['confidence']} ({forecast['prediction']['confidence_pct']}%)",
        "data": chart_data,
        "chart": chart_config,
        "error": None,
    }


def _is_conversational(question: str) -> bool:
    """Check if the question is conversational (not a data query)."""
    conversational_patterns = [
        r"^(hi|hello|hey|thanks|thank you|bye|goodbye|ok|okay)\b",
        r"^what can you do",
        r"^help\b",
        r"^who are you",
    ]
    q_lower = question.strip().lower()
    for pattern in conversational_patterns:
        if re.match(pattern, q_lower):
            return True
    return False


async def _handle_conversational(question: str, llm) -> str:
    """Handle non-data conversational messages."""
    q_lower = question.strip().lower()

    if any(q_lower.startswith(g) for g in ["hi", "hello", "hey"]):
        return (
            "Hello! I'm your data assistant for the Effect Manager grocery pricing database. "
            "I can help you explore product prices, compare retailers, analyze trends, and more. "
            "Try asking something like:\n\n"
            "• **What are the top 10 most expensive products at Bilka?**\n"
            "• **Compare average prices between Netto and Rema**\n"
            "• **Show me price trends for milk products over the last 6 months**\n"
            "• **Which retailer has the most products on promotion?**"
        )

    if "what can you do" in q_lower or "help" in q_lower:
        return (
            "I can query the Effect Manager database to answer questions about:\n\n"
            "📊 **Pricing**: Product prices, unit prices, discounted prices across retailers\n"
            "🏪 **Retailers**: Bilka, Føtex, Meny, Netto, Rema, SPAR, Min Købmand\n"
            "📦 **Products**: Categories, brands, EAN codes, stock status\n"
            "📈 **Trends**: Price changes over time (Apr 2025 – Mar 2026)\n"
            "🏷️ **Promotions**: Offer descriptions, multi-promo flags\n"
            "🔍 **Comparisons**: Cross-retailer price comparisons\n\n"
            "Just ask your question in natural language!"
        )

    if any(q_lower.startswith(t) for t in ["thanks", "thank you"]):
        return "You're welcome! Feel free to ask more questions about your data."

    return "I'm here to help with your grocery pricing data. What would you like to know?"
