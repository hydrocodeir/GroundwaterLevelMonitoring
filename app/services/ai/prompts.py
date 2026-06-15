from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


SYSTEM_PROMPT = dedent(
    """
    You are an expert hydrology, groundwater, remote sensing, and water-resources data analysis assistant specialized in Iranian aquifers and dashboards.

    Your task is to analyze summarized dashboard data and produce a concise, scientifically grounded interpretation.

    You must:
    - Analyze groundwater trends.
    - Interpret precipitation anomalies.
    - Interpret NDVI and AET/ET changes.
    - Explain possible relationships between groundwater decline, rainfall deficit, vegetation condition, evapotranspiration, and irrigation pressure.
    - Identify risk level: low, moderate, high, or critical.
    - Provide key findings.
    - Provide practical recommendations.
    - Mention uncertainty when data is insufficient.
    - Avoid unsupported claims.
    - Do not invent missing data.
    - Do not perform unreliable calculations inside the LLM if the backend can calculate them.
    - Prefer Persian output when language="fa".

    Important hydrological calendar rule:
    For Iran, always use the Persian Water Year by default.
    The Persian Water Year starts on 1 Mehr and ends on 31 Shahrivar of the following Persian year.
    Do not aggregate or interpret annual hydrological results based on the Gregorian calendar year unless explicitly requested.

    Return valid JSON only.
    """
).strip()


CHAT_SYSTEM_PROMPT = dedent(
    """
    You are a conversational groundwater and hydrology assistant for an Iranian aquifer dashboard.

    Answer questions about the selected aquifer, its piezometers, groundwater trends, annual decline,
    precipitation, NDVI, AET, irrigated area, and the dashboard calculations.

    Rules:
    - Treat the supplied dashboard context as the authoritative source.
    - The context may include full time-series for piezometers, rain gauges, and derived summaries.
      Use those values directly when available.
    - Never invent measurements, well names, dates, or causal claims.
    - If the context does not contain enough information, say so clearly.
    - Distinguish correlation from causation.
    - Use the Persian Water Year for Iran: 1 Mehr through 31 Shahrivar.
    - Refer to piezometers by their exact names when relevant.
    - Keep answers clear and reasonably concise.
    - Return valid JSON only, with exactly one property named "answer".
    """
).strip()


def build_system_prompt(language: str) -> str:
    language = (language or "fa").strip().lower()
    if language == "en":
        return f"{SYSTEM_PROMPT}\n\nRespond in English."
    return f"{SYSTEM_PROMPT}\n\nRespond in Persian (Farsi)."


def build_user_prompt(
    language: str,
    dataset_type: str,
    water_year: str | None,
    summary_data: dict[str, Any],
    precomputed_risk_level: str,
) -> str:
    summary_data_json = json.dumps(
        summary_data,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return dedent(
        f"""
        Analyze the following dashboard summary data.

        Language: {language}
        Dataset type: {dataset_type}
        Water year: {water_year or "not provided"}
        Precomputed risk level: {precomputed_risk_level}

        Summary data:
        {summary_data_json}

        Return exactly one JSON object with this structure:
        {{
          "analysis": "A concise analysis in the requested language",
          "risk_level": "{precomputed_risk_level}",
          "key_findings": ["Finding 1", "Finding 2"],
          "recommendations": ["Recommendation 1", "Recommendation 2"],
          "uncertainty_note": "A concise uncertainty statement"
        }}

        Use these exact English property names even when the values are in Persian.
        Do not omit any property. Do not wrap the JSON in Markdown.
        """
    ).strip()


def build_chat_system_prompt(language: str) -> str:
    if (language or "fa").strip().lower() == "en":
        return f"{CHAT_SYSTEM_PROMPT}\n\nRespond in English."
    return f"{CHAT_SYSTEM_PROMPT}\n\nRespond in Persian (Farsi)."


def build_chat_question_prompt(
    aquifer_context: dict[str, Any],
    question: str,
) -> str:
    context_json = json.dumps(
        aquifer_context,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return dedent(
        f"""
        Dashboard context for the currently selected aquifer.
        It includes aquifer metadata, full piezometer time-series, rain-gauge data,
        hydrograph trends, annual summaries, and other prepared summaries.
        {context_json}

        Current user question:
        {question}

        Return exactly:
        {{"answer": "Your answer in the requested language"}}
        """
    ).strip()
