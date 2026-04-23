# reports/services/comparison_engine.py
"""
Comparison Engine
=================
For any report request, automatically resolves a prior comparison period
and fetches both current + prior data via the existing ReportGeneratorService.

Comparison mode selection (default logic, overridable by user):
  - 'today' period  → compare to yesterday
  - range ≤ 7 days  → compare to same days last week
  - range ≤ 35 days → compare to previous calendar month
  - range > 35 days → compare to same period last year
  - user may pass   comparison_mode='prev_year' | 'prev_month' | 'prev_week'
                    | 'yesterday' | 'custom' + comparison_start/end

Usage in views:
    engine = ComparisonEngine(user, saved_report)
    result = engine.fetch(
        start_date=..., end_date=..., store_id=...,
        comparison_mode='auto'   # or 'prev_month', 'custom', etc.
    )
    result['current']    # data dict from report_generator
    result['prior']      # same structure, prior period
    result['prior_label']  # human label e.g. "March 2026"
    result['delta']      # flat dict of key numeric differences
"""

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

logger = logging.getLogger(__name__)


def _label_for_period(start_date, end_date) -> str:
    """Human-readable label for a date range."""
    if start_date is None and end_date is None:
        return "all time"
    if start_date == end_date:
        return start_date.strftime('%d %b %Y')
    if start_date and end_date:
        if start_date.year == end_date.year and start_date.month == end_date.month:
            return start_date.strftime('%B %Y')
        return f"{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}"
    if end_date:
        return f"up to {end_date.strftime('%d %b %Y')}"
    return f"from {start_date.strftime('%d %b %Y')}"


def _shift_period(start_date, end_date, mode: str, custom_start=None, custom_end=None):
    """
    Return (prior_start, prior_end) based on the comparison mode.
    """
    today = date.today()

    if mode == 'custom' and custom_start and custom_end:
        return custom_start, custom_end

    if start_date is None or end_date is None:
        # Can't shift an open-ended range automatically
        return None, None

    span = (end_date - start_date).days + 1  # inclusive

    if mode == 'yesterday':
        return start_date - timedelta(days=1), end_date - timedelta(days=1)

    if mode == 'prev_week':
        return start_date - timedelta(weeks=1), end_date - timedelta(weeks=1)

    if mode == 'prev_month':
        prior_start = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        # End = last day of prior month
        prior_end = start_date.replace(day=1) - timedelta(days=1)
        return prior_start, prior_end

    if mode == 'prev_year':
        try:
            prior_start = start_date.replace(year=start_date.year - 1)
            prior_end = end_date.replace(year=end_date.year - 1)
        except ValueError:
            # Feb 29 in non-leap year
            prior_start = start_date.replace(year=start_date.year - 1, day=28)
            prior_end = end_date.replace(year=end_date.year - 1, day=28)
        return prior_start, prior_end

    # --- auto mode ---
    # Single day
    if span == 1:
        return start_date - timedelta(days=1), end_date - timedelta(days=1)

    # ≤ 7 days: same days last week
    if span <= 7:
        return start_date - timedelta(weeks=1), end_date - timedelta(weeks=1)

    # ≤ 35 days: previous calendar month
    if span <= 35:
        prior_start = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        prior_end = start_date.replace(day=1) - timedelta(days=1)
        return prior_start, prior_end

    # > 35 days: same period last year
    try:
        prior_start = start_date.replace(year=start_date.year - 1)
        prior_end = end_date.replace(year=end_date.year - 1)
    except ValueError:
        prior_start = start_date.replace(year=start_date.year - 1, day=28)
        prior_end = end_date.replace(year=end_date.year - 1, day=28)
    return prior_start, prior_end


def _extract_key_metrics(data: dict) -> dict:
    """
    Pull a flat dict of the most important numeric values from any report
    data dict. Used to compute delta percentages for the narrative engine.
    """
    metrics = {}

    # Sales summary
    if 'summary' in data and isinstance(data['summary'], dict):
        s = data['summary']
        for key in ['total_sales', 'total_transactions', 'avg_transaction',
                    'total_tax', 'total_discount', 'total_expenses',
                    'total_amount', 'avg_expense', 'total_cashiers',
                    'avg_per_cashier']:
            if key in s:
                try:
                    metrics[key] = float(s[key] or 0)
                except (TypeError, ValueError):
                    pass

    # Profit & loss
    if 'profit_loss' in data:
        pl = data['profit_loss']
        for section in ('revenue', 'costs', 'profit'):
            if section in pl:
                for key, val in pl[section].items():
                    try:
                        metrics[f"pl_{key}"] = float(val or 0)
                    except (TypeError, ValueError):
                        pass

    # Inventory
    if 'summary' in data:
        s = data['summary']
        for key in ['total_stock_value', 'total_retail_value',
                    'low_stock_count', 'out_of_stock_count']:
            if key in s:
                try:
                    metrics[key] = float(s[key] or 0)
                except (TypeError, ValueError):
                    pass

    # EFRIS compliance rate
    if 'compliance' in data and isinstance(data['compliance'], dict):
        try:
            metrics['compliance_rate'] = float(
                data['compliance'].get('compliance_rate', 0) or 0
            )
        except (TypeError, ValueError):
            pass

    # Z-report
    if 'net_sales' in data:
        try:
            metrics['net_sales'] = float(data['net_sales'] or 0)
        except (TypeError, ValueError):
            pass

    return metrics


def _compute_deltas(current_metrics: dict, prior_metrics: dict) -> dict:
    """
    Returns a dict of {key: {current, prior, delta, pct_change, direction}}
    for every numeric metric present in both periods.
    """
    deltas = {}
    for key in current_metrics:
        if key not in prior_metrics:
            continue
        current_val = current_metrics[key]
        prior_val = prior_metrics[key]
        delta = current_val - prior_val
        if prior_val != 0:
            pct = (delta / abs(prior_val)) * 100
        else:
            pct = None

        direction = 'up' if delta > 0 else ('down' if delta < 0 else 'flat')

        deltas[key] = {
            'current': current_val,
            'prior': prior_val,
            'delta': delta,
            'pct_change': pct,
            'direction': direction,
        }
    return deltas


class ComparisonEngine:
    """
    Wraps ReportGeneratorService to fetch current + prior period data
    and return them together with computed deltas.
    """

    def __init__(self, user, saved_report):
        self.user = user
        self.saved_report = saved_report

    def fetch(self, start_date=None, end_date=None, store_id=None,
              comparison_mode: str = 'auto',
              comparison_start=None, comparison_end=None,
              **extra_kwargs) -> dict:
        """
        Fetch current period data, resolve prior period, fetch prior data,
        compute deltas. Returns a unified dict.
        """
        from .report_generator import ReportGeneratorService

        generator = ReportGeneratorService(self.user, self.saved_report)

        # ── Current period ──────────────────────────────────────────────
        current_kwargs = dict(
            start_date=start_date,
            end_date=end_date,
            store_id=store_id,
            **extra_kwargs
        )
        try:
            current_data = generator.generate(**current_kwargs)
        except Exception as exc:
            logger.error(f"ComparisonEngine: current period failed: {exc}", exc_info=True)
            raise

        # ── Prior period resolution ──────────────────────────────────────
        prior_start, prior_end = _shift_period(
            start_date, end_date,
            mode=comparison_mode,
            custom_start=comparison_start,
            custom_end=comparison_end,
        )

        prior_data = {}
        prior_label = None
        deltas = {}

        if prior_start and prior_end:
            prior_label = _label_for_period(prior_start, prior_end)
            prior_kwargs = dict(
                start_date=prior_start,
                end_date=prior_end,
                store_id=store_id,
                **extra_kwargs
            )
            try:
                # Create a fresh generator for the prior period
                # (reuses the same SavedReport, but fresh cache key)
                prior_generator = ReportGeneratorService(self.user, self.saved_report)
                prior_data = prior_generator.generate(**prior_kwargs)
                prior_data.pop('metadata', None)  # strip prior metadata

                # ── Deltas ───────────────────────────────────────────────
                current_metrics = _extract_key_metrics(current_data)
                prior_metrics = _extract_key_metrics(prior_data)
                deltas = _compute_deltas(current_metrics, prior_metrics)

            except Exception as exc:
                logger.warning(
                    f"ComparisonEngine: prior period fetch failed (non-fatal): {exc}"
                )
                prior_data = {}
                deltas = {}

        current_label = _label_for_period(start_date, end_date)

        return {
            'current': current_data,
            'prior': prior_data,
            'prior_label': prior_label or 'prior period',
            'current_label': current_label,
            'comparison_mode': comparison_mode,
            'prior_start': prior_start,
            'prior_end': prior_end,
            'delta': deltas,
        }