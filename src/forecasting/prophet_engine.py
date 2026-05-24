"""
Prophet-based probabilistic forecasting engine for SCDF.

Generates synthetic historical KPI time-series data shaped by disruption type,
then fits Prophet models to extract P10/P50/P90 confidence intervals.

Run standalone to test:
    python -m src.forecasting.prophet_engine
"""

import logging
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from pydantic import BaseModel

# Silence Prophet / Stan's verbose output
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*Importing plotly failed.*")
warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class DisruptionForecastInput(BaseModel):
    """Parameters that drive the synthetic series generation and Prophet fit."""

    disruption_type: str          # weather | port | tariff | demand | geopolitical
    region: str
    severity_score: int           # 1-10
    baseline_lead_time_days: int = 14
    baseline_inventory_units: int = 10_000
    baseline_service_level_pct: float = 95.0
    historical_volatility: float = 0.15   # std dev as fraction of baseline


# ---------------------------------------------------------------------------
# Disruption pattern shapes
# ---------------------------------------------------------------------------

def _severity_multiplier(severity: int) -> float:
    """Map severity 1-10 to an impact scale factor (1× → 3×)."""
    return 1.0 + (severity - 1) * (2.0 / 9.0)


def _port_pattern(days: np.ndarray, severity: int) -> dict[str, np.ndarray]:
    """Sharp lead-time spike at day 300-330; inventory follows 7 days later."""
    scale = _severity_multiplier(severity)
    lead_spike = np.zeros(len(days))
    inv_drop = np.zeros(len(days))
    svc_drop = np.zeros(len(days))

    for i, d in enumerate(days):
        if 300 <= d <= 330:
            lead_spike[i] = scale * 12 * (1 - abs(d - 315) / 15)
        if 307 <= d <= 340:
            inv_drop[i] = -scale * 1500 * (1 - abs(d - 322) / 18)
        if 305 <= d <= 335:
            svc_drop[i] = -scale * 6 * (1 - abs(d - 318) / 15)

    return {"lead_time": lead_spike, "inventory_level": inv_drop, "service_level": svc_drop}


def _weather_pattern(days: np.ndarray, severity: int) -> dict[str, np.ndarray]:
    """Gradual lead-time ramp over 2 weeks, then recovery."""
    scale = _severity_multiplier(severity)
    lead_ramp = np.zeros(len(days))
    inv_drop = np.zeros(len(days))
    svc_drop = np.zeros(len(days))

    for i, d in enumerate(days):
        if 285 <= d <= 299:
            lead_ramp[i] = scale * 6 * (d - 285) / 14
        if 300 <= d <= 320:
            lead_ramp[i] = scale * 6 * max(0, 1 - (d - 300) / 20)
        if 295 <= d <= 318:
            inv_drop[i] = -scale * 800 * (1 - abs(d - 306) / 12)
        if 295 <= d <= 318:
            svc_drop[i] = -scale * 4 * (1 - abs(d - 306) / 12)

    return {"lead_time": lead_ramp, "inventory_level": inv_drop, "service_level": svc_drop}


def _tariff_pattern(days: np.ndarray, severity: int) -> dict[str, np.ndarray]:
    """Step-change: companies pre-buy (inventory spike), then normalisation."""
    scale = _severity_multiplier(severity)
    lead_step = np.zeros(len(days))
    inv_step = np.zeros(len(days))
    svc_step = np.zeros(len(days))

    for i, d in enumerate(days):
        if 290 <= d <= 310:
            # Pre-buy surge
            inv_step[i] = scale * 2500
        if d > 310:
            # Drawdown after tariff hits
            inv_step[i] = -scale * 1200 * min(1, (d - 310) / 30)
        if d >= 305:
            lead_step[i] = scale * 4
            svc_step[i] = -scale * 3

    return {"lead_time": lead_step, "inventory_level": inv_step, "service_level": svc_step}


def _demand_pattern(days: np.ndarray, severity: int) -> dict[str, np.ndarray]:
    """Service level drops first, inventory depletes within 30 days."""
    scale = _severity_multiplier(severity)
    lead = np.zeros(len(days))
    inv = np.zeros(len(days))
    svc = np.zeros(len(days))

    for i, d in enumerate(days):
        if d >= 300:
            elapsed = min(d - 300, 30)
            svc[i] = -scale * 7 * (elapsed / 30)
            inv[i] = -scale * 2000 * (elapsed / 30)
            lead[i] = scale * 3 * (elapsed / 30)

    return {"lead_time": lead, "inventory_level": inv, "service_level": svc}


def _geopolitical_pattern(days: np.ndarray, severity: int) -> dict[str, np.ndarray]:
    """All three KPIs affected simultaneously; longer, slower recovery."""
    scale = _severity_multiplier(severity)
    lead = np.zeros(len(days))
    inv = np.zeros(len(days))
    svc = np.zeros(len(days))

    for i, d in enumerate(days):
        if 290 <= d <= 365:
            decay = max(0, 1 - (d - 290) / 75)
            lead[i] = scale * 15 * decay
            inv[i] = -scale * 2200 * decay
            svc[i] = -scale * 9 * decay

    return {"lead_time": lead, "inventory_level": inv, "service_level": svc}


_PATTERN_MAP = {
    "port": _port_pattern,
    "weather": _weather_pattern,
    "tariff": _tariff_pattern,
    "demand": _demand_pattern,
    "geopolitical": _geopolitical_pattern,
}


# ---------------------------------------------------------------------------
# Series generation
# ---------------------------------------------------------------------------

def generate_historical_series(inp: DisruptionForecastInput) -> pd.DataFrame:
    """
    Generate 365 days of synthetic KPI history shaped by the disruption type.

    Returns a long-format DataFrame with columns: ds, y, kpi_name.
    Each KPI (lead_time, inventory_level, service_level) gets its own rows.
    Noise is scaled by severity and the baseline volatility parameter.
    """
    rng = np.random.default_rng(seed=hash(f"{inp.disruption_type}-{inp.region}-{inp.severity_score}") % (2**31))
    days = np.arange(365)
    start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)

    pattern_fn = _PATTERN_MAP.get(inp.disruption_type, _geopolitical_pattern)
    patterns = pattern_fn(days, inp.severity_score)

    # Baselines
    baselines = {
        "lead_time": float(inp.baseline_lead_time_days),
        "inventory_level": float(inp.baseline_inventory_units),
        "service_level": inp.baseline_service_level_pct,
    }

    records = []
    for kpi, baseline in baselines.items():
        noise_std = baseline * inp.historical_volatility
        noise = rng.normal(0, noise_std, len(days))
        values = baseline + patterns[kpi] + noise

        # Clip to physical bounds
        if kpi == "service_level":
            values = np.clip(values, 0, 100)
        elif kpi in ("lead_time", "inventory_level"):
            values = np.clip(values, 0, None)

        for d, v in zip(days, values):
            records.append({
                "ds": start_date + timedelta(days=int(d)),
                "y": float(v),
                "kpi_name": kpi,
            })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Prophet forecast
# ---------------------------------------------------------------------------

def run_prophet_forecast(series: pd.DataFrame, kpi_name: str, periods: int = 30) -> dict:
    """
    Fit a Prophet model on the given series and extract P10/P50/P90 values.

    Args:
        series:   Full historical DataFrame (all KPIs). Filtered internally by kpi_name.
        kpi_name: One of: lead_time | inventory_level | service_level
        periods:  Forecast horizon in days.

    Returns:
        Dict with keys: p10, p50, p90, trend ("improving"|"stable"|"worsening")
        Falls back to baseline-derived values if Prophet fails.
    """
    # Filter to the requested KPI
    kpi_df = series[series["kpi_name"] == kpi_name][["ds", "y"]].copy()
    kpi_df = kpi_df.sort_values("ds").reset_index(drop=True)

    try:
        from prophet import Prophet  # import inside to avoid module-level import cost

        model = Prophet(
            interval_width=0.80,   # gives ~P10/P90 uncertainty
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(kpi_df)

        future = model.make_future_dataframe(periods=periods, freq="D")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = model.predict(future)

        # Forecast horizon rows only
        horizon = forecast.tail(periods)

        # P10 = worst: lower bound of yhat_lower; P90 = best: upper bound of yhat_upper
        p10 = float(horizon["yhat_lower"].min())
        p50 = float(horizon["yhat"].mean())
        p90 = float(horizon["yhat_upper"].max())

        # Clip to physical bounds
        if kpi_name == "service_level":
            p10, p50, p90 = (
                max(0.0, min(100.0, p10)),
                max(0.0, min(100.0, p50)),
                max(0.0, min(100.0, p90)),
            )
        else:
            p10, p50, p90 = max(0.0, p10), max(0.0, p50), max(0.0, p90)

        # Trend direction from slope of last-30-day yhat
        last_30 = forecast.tail(30)["yhat"]
        trend_slope = float(last_30.iloc[-1] - last_30.iloc[0])
        if kpi_name == "lead_time":
            # For lead time, rising is bad (worsening)
            trend = "worsening" if trend_slope > 0.5 else ("improving" if trend_slope < -0.5 else "stable")
        else:
            trend = "improving" if trend_slope > 0.5 else ("worsening" if trend_slope < -0.5 else "stable")

        return {"p10": p10, "p50": p50, "p90": p90, "trend": trend}

    except Exception as exc:
        logging.warning(f"Prophet fit failed for {kpi_name}: {exc} — using fallback")
        baseline = kpi_df["y"].mean()
        return {
            "p10": baseline * 0.7,
            "p50": baseline,
            "p90": baseline * 1.3,
            "trend": "stable",
        }


# ---------------------------------------------------------------------------
# Scenario set assembly
# ---------------------------------------------------------------------------

def _resolution_days(severity: int) -> tuple[int, int, int]:
    """Return (p10_days, p50_days, p90_days) based on severity band."""
    if severity <= 3:
        return 14, 7, 3
    elif severity <= 6:
        return 35, 14, 7
    elif severity <= 8:
        return 56, 21, 10
    else:
        return 90, 35, 14


def generate_scenario_set(inp: DisruptionForecastInput) -> dict:
    """
    Run Prophet forecasts for all three KPIs and assemble a ScenarioSet dict.

    The returned dict has keys matching ScenarioSet field names exactly.
    signal_id is NOT set here — the calling agent injects it.

    P10 (worst case): uses pessimistic tail values across all KPIs.
    P50 (base case):  uses median forecast values.
    P90 (best case):  uses optimistic tail values across all KPIs.
    """
    series = generate_historical_series(inp)

    lead = run_prophet_forecast(series, "lead_time")
    inv = run_prophet_forecast(series, "inventory_level")
    svc = run_prophet_forecast(series, "service_level")

    baseline_lead = float(inp.baseline_lead_time_days)
    baseline_inv = float(inp.baseline_inventory_units)
    baseline_svc = float(inp.baseline_service_level_pct)

    res_p10, res_p50, res_p90 = _resolution_days(inp.severity_score)

    def pct_change(forecast_val: float, baseline: float) -> float:
        if baseline == 0:
            return 0.0
        return round((forecast_val - baseline) / baseline * 100, 1)

    # Uncertainty width as a proxy for forecast confidence
    lead_width = abs(lead["p90"] - lead["p10"]) / max(baseline_lead, 1)
    confidence = float(np.clip(1.0 - lead_width / 5.0, 0.30, 0.95))

    # Compute MAE proxy for data quality note
    mae_proxy = round(abs(lead["p50"] - baseline_lead), 1)

    def _narrative(label: str, lead_days: float, inv_pct: float, svc_pct: float, res_days: int, inp: DisruptionForecastInput) -> str:
        direction = "increases" if lead_days > 0 else "decreases"
        inv_dir = "declines" if inv_pct < 0 else "grows"
        svc_dir = "drops" if svc_pct < 0 else "improves"
        return (
            f"{label} scenario: lead time {direction} by {abs(lead_days):.0f} days, "
            f"inventory {inv_dir} {abs(inv_pct):.1f}%, "
            f"service level {svc_dir} {abs(svc_pct):.1f}%. "
            f"Estimated resolution: {res_days} days for {inp.disruption_type} in {inp.region}."
        )

    # For lead_time: HIGHER = WORSE (more days of delay).
    #   P10 (worst) uses yhat_upper (highest lead time) = lead["p90"]
    #   P90 (best)  uses yhat_lower (lowest lead time)  = lead["p10"]
    # For inventory / service_level: LOWER = WORSE.
    #   P10 (worst) uses yhat_lower (lowest value)  = inv/svc["p10"]
    #   P90 (best)  uses yhat_upper (highest value) = inv/svc["p90"]

    # P10 — worst case
    p10_lead_impact = round(lead["p90"] - baseline_lead, 1)   # highest lead time
    p10_inv_pct = pct_change(inv["p10"], baseline_inv)         # lowest inventory
    p10_svc_pct = pct_change(svc["p10"], baseline_svc)         # lowest service level

    # P50 — base case (median across all KPIs)
    p50_lead_impact = round(lead["p50"] - baseline_lead, 1)
    p50_inv_pct = pct_change(inv["p50"], baseline_inv)
    p50_svc_pct = pct_change(svc["p50"], baseline_svc)

    # P90 — best case
    p90_lead_impact = round(lead["p10"] - baseline_lead, 1)   # lowest lead time
    p90_inv_pct = pct_change(inv["p90"], baseline_inv)         # highest inventory
    p90_svc_pct = pct_change(svc["p90"], baseline_svc)         # highest service level

    return {
        "p10": {
            "label": "P10 (worst case)",
            "probability": 0.10,
            "description": _narrative("P10 worst-case", p10_lead_impact, p10_inv_pct, p10_svc_pct, res_p10, inp),
            "inventory_impact_pct": p10_inv_pct,
            "lead_time_impact_days": int(p10_lead_impact),
            "service_level_impact_pct": p10_svc_pct,
            "resolution_days_estimate": res_p10,
        },
        "p50": {
            "label": "P50 (base case)",
            "probability": 0.50,
            "description": _narrative("P50 base-case", p50_lead_impact, p50_inv_pct, p50_svc_pct, res_p50, inp),
            "inventory_impact_pct": p50_inv_pct,
            "lead_time_impact_days": int(p50_lead_impact),
            "service_level_impact_pct": p50_svc_pct,
            "resolution_days_estimate": res_p50,
        },
        "p90": {
            "label": "P90 (best case)",
            "probability": 0.90,
            "description": _narrative("P90 best-case", p90_lead_impact, p90_inv_pct, p90_svc_pct, res_p90, inp),
            "inventory_impact_pct": p90_inv_pct,
            "lead_time_impact_days": int(p90_lead_impact),
            "service_level_impact_pct": p90_svc_pct,
            "resolution_days_estimate": res_p90,
        },
        "forecast_confidence": round(confidence, 3),
        "data_quality_note": (
            f"Prophet forecast on synthetic historical series. "
            f"Disruption type: {inp.disruption_type}, region: {inp.region}, severity: {inp.severity_score}. "
            f"Lead time MAE proxy: {mae_proxy} days."
        ),
    }


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.console import Console
    from rich.pretty import Pretty

    console = Console()
    console.rule("[bold cyan]SCDF Prophet Forecast Test[/bold cyan]")

    test_input = DisruptionForecastInput(
        disruption_type="port",
        region="Asia-Pacific",
        severity_score=7,
        baseline_lead_time_days=21,
        baseline_inventory_units=10_000,
        baseline_service_level_pct=95.0,
    )
    console.print(f"Input: {test_input.model_dump()}")
    console.rule("Running Prophet forecast...")

    result = generate_scenario_set(test_input)
    console.print(Pretty(result))
    console.rule("[bold green]Done[/bold green]")
