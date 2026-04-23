# reports/services/narrative_engine.py
"""
Narrative Engine
================
Converts numeric report data into human-readable paragraph explanations.
No AI — pure conditional logic on the actual numbers.

Each reporter class takes:
  - data        : current period dict from report_generator
  - prior       : prior period dict (may be empty {})
  - delta       : delta dict from comparison_engine
  - fmt         : CurrencyFormatter instance
  - period_label: human label for the current period
  - prior_label : human label for the prior period
  - reader_role : 'owner' | 'manager' | 'accountant' | 'auditor' | 'limited'

Returns a list of NarrativeBlock objects.

Usage:
    from .narrative_engine import build_narratives
    blocks = build_narratives(
        report_type='SALES_SUMMARY',
        data=current_data,
        prior=prior_data,
        delta=deltas,
        fmt=currency_formatter,
        period_label='April 2026',
        prior_label='March 2026',
        reader_role='owner',
    )
    # blocks[i].section, blocks[i].heading, blocks[i].paragraphs, blocks[i].insight
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NarrativeBlock:
    section: str          # ties to a PDF section key
    heading: str          # section heading text
    paragraphs: List[str] = field(default_factory=list)   # body paragraphs
    insight: Optional[str] = None   # callout box text (warning/tip)
    insight_level: str = 'info'     # 'info' | 'warning' | 'danger' | 'success'


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_float(val, default=0.0) -> float:
    try:
        return float(val or default)
    except (TypeError, ValueError):
        return default


def _growth_sentence(metric_label: str, pct: float | None, delta_dict: dict,
                     key: str, fmt) -> str:
    """
    Produce a single sentence describing growth/decline for a metric.
    e.g. "This represents a 12.4% increase over the prior period
          (UGX 4,982,000 more than before)."
    """
    if pct is None:
        return f"No prior period data is available to compare {metric_label}."

    direction = "increase" if pct >= 0 else "decrease"
    abs_pct = abs(pct)
    delta_val = delta_dict.get(key, {}).get('delta', 0)
    delta_str = fmt.format_delta(
        delta_dict.get(key, {}).get('current', 0),
        delta_dict.get(key, {}).get('prior', 0)
    )

    if abs_pct >= 20:
        qualifier = "a substantial"
    elif abs_pct >= 10:
        qualifier = "a strong"
    elif abs_pct >= 5:
        qualifier = "a healthy"
    elif abs_pct >= 1:
        qualifier = "a modest"
    else:
        qualifier = "a minimal"

    return (
        f"This represents {qualifier} {direction} of {abs_pct:.1f}% "
        f"compared to the prior period ({delta_str})."
    )


def _trend_tone(pct: float | None) -> str:
    """Return a qualitative tone word for a percentage change."""
    if pct is None:
        return "stable"
    if pct >= 20:
        return "exceptional"
    if pct >= 10:
        return "strong"
    if pct >= 3:
        return "positive"
    if pct >= -3:
        return "stable"
    if pct >= -10:
        return "slightly declining"
    return "significantly declining"


def _peak_day(grouped_data: list, amount_key='total_amount', date_key='date') -> tuple:
    """Return (date_str, amount) for the day with highest amount."""
    if not grouped_data:
        return None, 0
    best = max(grouped_data, key=lambda d: _safe_float(d.get(amount_key, 0)))
    return best.get(date_key), _safe_float(best.get(amount_key, 0))


# ── role gate ─────────────────────────────────────────────────────────────────

ROLE_PRIORITY = {
    'owner': 100,
    'manager': 70,
    'accountant': 40,
    'auditor': 35,
    'limited': 10,
}


def _reader_has_access(reader_role: str, min_role: str) -> bool:
    priority = ROLE_PRIORITY.get(reader_role, 0)
    threshold = ROLE_PRIORITY.get(min_role, 0)
    return priority >= threshold


# ── individual narrators ───────────────────────────────────────────────────────

class SalesNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        summary = data.get('summary', {})
        grouped = data.get('grouped_data', [])
        payment_methods = data.get('payment_methods', [])
        top_products = data.get('top_products', [])

        total_sales = _safe_float(summary.get('total_sales'))
        transactions = int(summary.get('total_transactions') or 0)
        avg_tx = _safe_float(summary.get('avg_transaction'))
        total_tax = _safe_float(summary.get('total_tax'))
        total_discount = _safe_float(summary.get('total_discount'))

        pct_change = delta.get('total_sales', {}).get('pct_change')
        prior_total = delta.get('total_sales', {}).get('prior', 0)
        tone = _trend_tone(pct_change)

        # ── Revenue overview ──────────────────────────────────────────────
        peak_date, peak_amt = _peak_day(grouped)

        if transactions == 0:
            para1 = (
                f"No completed sales were recorded for {period_label}. "
                f"Ensure that all transactions have been properly finalised "
                f"and that the correct date range and store filters are selected."
            )
            blocks.append(NarrativeBlock(
                section='revenue',
                heading='Revenue Performance',
                paragraphs=[para1],
                insight="No sales data found for this period. Verify filters.",
                insight_level='warning',
            ))
            return blocks

        para1_parts = [
            f"During {period_label}, your business generated "
            f"{fmt.format(total_sales)} in gross revenue across "
            f"{transactions:,} completed transactions — an average of "
            f"{fmt.format(avg_tx)} per sale."
        ]

        growth_sent = _growth_sentence('revenue', pct_change, delta,
                                       'total_sales', fmt)
        para1_parts.append(growth_sent)

        if peak_date:
            para1_parts.append(
                f"The highest revenue day was {peak_date} with "
                f"{fmt.format(peak_amt)} in sales."
            )

        if total_discount > 0:
            disc_pct = (total_discount / total_sales * 100) if total_sales > 0 else 0
            para1_parts.append(
                f"Discounts totalling {fmt.format(total_discount)} "
                f"({disc_pct:.1f}% of gross revenue) were applied during this period."
            )

        if total_tax > 0:
            para1_parts.append(
                f"Tax collected amounted to {fmt.format(total_tax)}."
            )

        insight = None
        insight_level = 'info'
        if pct_change is not None and pct_change < -10:
            insight = (
                f"Revenue has declined {abs(pct_change):.1f}% compared to "
                f"{prior_label}. Review pricing, stock availability, and "
                f"staffing levels to identify the cause."
            )
            insight_level = 'danger'
        elif pct_change is not None and pct_change > 15:
            insight = (
                f"Revenue is up {pct_change:.1f}% versus {prior_label} — "
                f"an excellent result. Identify what drove this performance "
                f"and replicate it in coming periods."
            )
            insight_level = 'success'

        blocks.append(NarrativeBlock(
            section='revenue',
            heading='Revenue Performance',
            paragraphs=[' '.join(para1_parts)],
            insight=insight,
            insight_level=insight_level,
        ))

        # ── Payment methods ───────────────────────────────────────────────
        if payment_methods and _reader_has_access(reader_role, 'limited'):
            top_method = payment_methods[0] if payment_methods else {}
            top_method_name = top_method.get('payment_method', 'Unknown')
            top_method_pct = _safe_float(top_method.get('percentage'))
            method_count = len(payment_methods)

            para = (
                f"Payments were received via {method_count} method(s). "
                f"{top_method_name} was the most used, accounting for "
                f"{top_method_pct:.1f}% of total revenue."
            )
            if method_count > 1:
                others = ', '.join(
                    pm.get('payment_method', '') for pm in payment_methods[1:3]
                )
                para += f" Other methods included {others}."

            blocks.append(NarrativeBlock(
                section='payment_methods',
                heading='Payment Method Breakdown',
                paragraphs=[para],
            ))

        # ── Top products ──────────────────────────────────────────────────
        if top_products and _reader_has_access(reader_role, 'limited'):
            names = [p.get('product__name', 'Unknown') for p in top_products[:3]]
            top_rev = _safe_float(top_products[0].get('revenue')) if top_products else 0

            para = (
                f"Your top-selling product was {names[0]} with "
                f"{fmt.format(top_rev)} in revenue for this period."
            )
            if len(names) > 1:
                para += f" This was followed by {' and '.join(names[1:])}."
            para += (
                f" Focus on ensuring these high-performers remain well-stocked "
                f"at all times."
            )
            blocks.append(NarrativeBlock(
                section='top_products',
                heading='Best-Selling Products',
                paragraphs=[para],
            ))

        return blocks


class ProfitNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        pl = data.get('profit_loss', {})
        revenue_data = pl.get('revenue', {})
        costs_data = pl.get('costs', {})
        profit_data = pl.get('profit', {})
        category_profit = data.get('category_profit', [])

        gross_rev = _safe_float(revenue_data.get('gross_revenue'))
        net_rev = _safe_float(revenue_data.get('net_revenue'))
        cogs = _safe_float(costs_data.get('cost_of_goods_sold'))
        gross_profit = _safe_float(profit_data.get('gross_profit'))
        gross_margin = _safe_float(profit_data.get('gross_margin'))
        net_profit = _safe_float(profit_data.get('net_profit'))
        net_margin = _safe_float(profit_data.get('net_margin'))

        pct_net = delta.get('pl_net_profit', {}).get('pct_change')
        pct_gross = delta.get('pl_gross_profit', {}).get('pct_change')

        # ── P&L overview ─────────────────────────────────────────────────
        if gross_rev == 0:
            blocks.append(NarrativeBlock(
                section='profit_loss',
                heading='Profit & Loss Statement',
                paragraphs=["No revenue data is available for this period."],
                insight="No sales recorded. Check date range and store selection.",
                insight_level='warning',
            ))
            return blocks

        # Margin health
        if gross_margin >= 40:
            margin_health = "strong and healthy"
        elif gross_margin >= 25:
            margin_health = "acceptable"
        elif gross_margin >= 10:
            margin_health = "thin — cost management should be reviewed"
        else:
            margin_health = "critically low — immediate review required"

        profit_verdict = "profitable" if net_profit > 0 else "operating at a loss"

        para = (
            f"For {period_label}, the business generated {fmt.format(gross_rev)} "
            f"in gross revenue. After deducting the cost of goods sold "
            f"({fmt.format(cogs)}), the gross profit stands at "
            f"{fmt.format(gross_profit)}, representing a gross margin of "
            f"{gross_margin:.1f}% — which is {margin_health}. "
            f"After accounting for tax and discounts, the business is {profit_verdict} "
            f"with a net profit of {fmt.format(net_profit)} "
            f"(net margin: {net_margin:.1f}%)."
        )

        growth_sent = _growth_sentence('net profit', pct_net, delta,
                                       'pl_net_profit', fmt)
        para += f" {growth_sent}"

        insight = None
        insight_level = 'info'
        if net_profit < 0:
            insight = (
                f"The business recorded a net loss of {fmt.format(abs(net_profit))} "
                f"this period. Review your cost of goods and operating expenses "
                f"urgently."
            )
            insight_level = 'danger'
        elif gross_margin < 15:
            insight = (
                f"Gross margin is below 15% — your cost of goods sold is consuming "
                f"most of your revenue. Consider renegotiating supplier prices or "
                f"adjusting selling prices."
            )
            insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='profit_loss',
            heading='Profit & Loss Statement',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        # ── Category breakdown ────────────────────────────────────────────
        if category_profit and _reader_has_access(reader_role, 'manager'):
            best_cat = max(category_profit, key=lambda c: _safe_float(c.get('margin', 0)),
                           default=None)
            worst_cat = min(category_profit, key=lambda c: _safe_float(c.get('margin', 0)),
                            default=None)

            cat_para = f"Across {len(category_profit)} product categories, "
            if best_cat:
                cat_para += (
                    f"{best_cat.get('category', 'Unknown')} delivered the highest margin "
                    f"at {_safe_float(best_cat.get('margin')):.1f}%. "
                )
            if worst_cat and worst_cat != best_cat:
                wm = _safe_float(worst_cat.get('margin', 0))
                cat_para += (
                    f"{worst_cat.get('category', 'Unknown')} had the lowest margin "
                    f"({wm:.1f}%)"
                )
                if wm < 10:
                    cat_para += " — consider whether this category is viable at current pricing."
                else:
                    cat_para += "."

            blocks.append(NarrativeBlock(
                section='category_profit',
                heading='Profitability by Category',
                paragraphs=[cat_para],
            ))

        return blocks


class InventoryNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        summary = data.get('summary', {})
        alerts = data.get('alerts', [])
        category_summary = data.get('category_summary', [])

        total_products = int(summary.get('total_products') or 0)
        low_stock = int(summary.get('low_stock_count') or 0)
        out_of_stock = int(summary.get('out_of_stock_count') or 0)
        total_value = _safe_float(summary.get('total_stock_value'))
        retail_value = _safe_float(summary.get('total_retail_value'))
        total_qty = _safe_float(summary.get('total_quantity'))

        in_stock = total_products - low_stock - out_of_stock
        health_pct = (in_stock / total_products * 100) if total_products > 0 else 0

        if health_pct >= 90:
            health_label = "excellent"
        elif health_pct >= 75:
            health_label = "good"
        elif health_pct >= 50:
            health_label = "moderate — attention needed"
        else:
            health_label = "poor — immediate restocking required"

        para = (
            f"As of this report, your inventory covers {total_products:,} product "
            f"stock entries across all tracked locations. "
            f"{in_stock:,} items ({health_pct:.0f}%) are at healthy stock levels, "
            f"while {low_stock:,} are running low and {out_of_stock:,} are completely "
            f"out of stock. Overall stock health is {health_label}. "
            f"The total inventory is valued at {fmt.format(total_value)} at cost price, "
            f"with a retail value of {fmt.format(retail_value)}."
        )

        insight = None
        insight_level = 'info'
        if out_of_stock > 0:
            top_oos = alerts[:3]
            products_listed = ', '.join(
                a.get('product__name', 'Unknown') for a in top_oos
            )
            insight = (
                f"{out_of_stock} item(s) are out of stock and cannot be sold. "
                f"Priority items to restock: {products_listed}."
            )
            insight_level = 'danger' if out_of_stock > 5 else 'warning'
        elif low_stock > 0:
            insight = (
                f"{low_stock} item(s) are below their reorder threshold. "
                f"Place purchase orders soon to avoid stockouts."
            )
            insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='inventory',
            heading='Inventory Health Overview',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class ExpenseNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        summary = data.get('summary', {})
        tag_breakdown = data.get('tag_breakdown', [])
        budget_analysis = data.get('budget_analysis', [])
        monthly_trend = data.get('monthly_trend', [])

        total = _safe_float(summary.get('total_amount'))
        count = int(summary.get('total_expenses') or 0)
        avg = _safe_float(summary.get('avg_expense'))
        recurring = int(summary.get('recurring_expenses') or 0)
        important = int(summary.get('important_expenses') or 0)

        pct_change = delta.get('total_amount', {}).get('pct_change')
        tone = _trend_tone(pct_change)

        if count == 0:
            blocks.append(NarrativeBlock(
                section='expenses',
                heading='Expense Summary',
                paragraphs=[f"No expenses were recorded for {period_label}."],
            ))
            return blocks

        para = (
            f"During {period_label}, {count:,} expense entries were recorded "
            f"totalling {fmt.format(total)}, with an average of "
            f"{fmt.format(avg)} per expense. "
        )

        if pct_change is not None:
            direction = "up" if pct_change > 0 else "down"
            para += (
                f"Spending is {direction} {abs(pct_change):.1f}% compared to "
                f"{prior_label}. "
            )

        if recurring > 0:
            para += (
                f"{recurring} of these are recurring expenses — these are "
                f"predictable and should be factored into budget planning. "
            )

        if important > 0:
            para += f"{important} expense(s) were flagged as important."

        # Top category
        insight = None
        insight_level = 'info'
        if tag_breakdown:
            top_tag = tag_breakdown[0]
            tag_pct = (top_tag['total_amount'] / total * 100) if total > 0 else 0
            insight = (
                f"'{top_tag['tag_name']}' is the largest expense category, "
                f"accounting for {fmt.format(top_tag['total_amount'])} "
                f"({tag_pct:.1f}% of total spending)."
            )
            insight_level = 'info'

        # Over-budget alert
        over_budget = [b for b in budget_analysis if b.get('over_budget')]
        if over_budget:
            names = ', '.join(b['budget_name'] for b in over_budget[:3])
            insight = (
                f"{len(over_budget)} budget(s) exceeded: {names}. "
                f"Review and adjust spending in these categories."
            )
            insight_level = 'danger'

        blocks.append(NarrativeBlock(
            section='expenses',
            heading='Expense Summary',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class CashierNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        performance = data.get('performance', [])
        summary = data.get('summary', {})

        total_cashiers = int(summary.get('total_cashiers') or 0)
        total_sales = _safe_float(summary.get('total_sales'))
        total_txns = int(summary.get('total_transactions') or 0)
        avg_per_cashier = _safe_float(summary.get('avg_per_cashier'))

        if total_cashiers == 0:
            blocks.append(NarrativeBlock(
                section='cashier',
                heading='Cashier Performance',
                paragraphs=[f"No cashier data was found for {period_label}."],
            ))
            return blocks

        top = performance[0] if performance else {}
        top_name = (
            f"{top.get('created_by__first_name', '')} "
            f"{top.get('created_by__last_name', '')}".strip()
            or 'Unknown'
        )
        top_sales = _safe_float(top.get('total_sales'))
        top_txns = int(top.get('transaction_count') or 0)

        bottom = performance[-1] if len(performance) > 1 else {}
        bottom_name = (
            f"{bottom.get('created_by__first_name', '')} "
            f"{bottom.get('created_by__last_name', '')}".strip()
            or 'Unknown'
        )
        bottom_sales = _safe_float(bottom.get('total_sales'))

        para = (
            f"During {period_label}, {total_cashiers} cashier(s) processed "
            f"{total_txns:,} transactions worth {fmt.format(total_sales)}. "
            f"The average revenue per cashier was {fmt.format(avg_per_cashier)}. "
            f"{top_name} was the top performer with {fmt.format(top_sales)} "
            f"across {top_txns:,} transactions."
        )

        if len(performance) > 1 and bottom_name != top_name:
            gap = top_sales - bottom_sales
            para += (
                f" {bottom_name} recorded the lowest sales at "
                f"{fmt.format(bottom_sales)} — a gap of {fmt.format(gap)} "
                f"from the top performer."
            )

        insight = None
        insight_level = 'info'
        if len(performance) >= 2:
            gap_pct = ((top_sales - bottom_sales) / top_sales * 100) if top_sales > 0 else 0
            if gap_pct > 50:
                insight = (
                    f"There is a significant performance gap ({gap_pct:.0f}%) "
                    f"between your top and bottom cashiers. Consider additional "
                    f"training or reviewing shift allocation."
                )
                insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='cashier',
            heading='Cashier Performance',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class TaxNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        summary = data.get('summary', {})
        tax_breakdown = data.get('tax_breakdown', [])
        efris_stats = data.get('efris_stats', {})

        total_sales = _safe_float(summary.get('total_sales_amount'))
        total_tax = _safe_float(summary.get('total_tax_collected'))
        total_txns = int(summary.get('total_transactions') or 0)
        effective_rate = (total_tax / total_sales * 100) if total_sales > 0 else 0
        compliance_rate = _safe_float(efris_stats.get('compliance_rate'))
        fiscalized = int(efris_stats.get('fiscalized') or 0)
        pending = int(efris_stats.get('pending') or 0)

        para = (
            f"For {period_label}, {total_txns:,} transactions generated total "
            f"sales of {fmt.format(total_sales)}, of which {fmt.format(total_tax)} "
            f"was collected as tax — an effective tax rate of {effective_rate:.1f}%. "
        )

        if tax_breakdown:
            rates = [f"{b['tax_rate_display']} ({fmt.format(b['total_tax'])})"
                     for b in tax_breakdown[:3]]
            para += f"Tax was collected across these rate bands: {', '.join(rates)}. "

        para += (
            f"EFRIS fiscalization compliance stands at {compliance_rate:.1f}% "
            f"({fiscalized:,} invoices fiscalized, {pending:,} pending)."
        )

        insight = None
        insight_level = 'info'
        if compliance_rate < 95 and total_txns > 0:
            insight = (
                f"EFRIS compliance is at {compliance_rate:.1f}% — {pending:,} "
                f"transaction(s) are not yet fiscalized. Resolve pending invoices "
                f"to remain compliant with URA requirements."
            )
            insight_level = 'danger' if compliance_rate < 80 else 'warning'

        blocks.append(NarrativeBlock(
            section='tax',
            heading='Tax Collection & EFRIS Compliance',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class EFRISNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        compliance = data.get('compliance', {})
        store_breakdown = data.get('store_breakdown', [])
        failed_sales = data.get('failed_sales', [])

        total = int(compliance.get('total_sales') or 0)
        fiscalized = int(compliance.get('fiscalized') or 0)
        pending = int(compliance.get('pending') or 0)
        rate = _safe_float(compliance.get('compliance_rate'))

        if total == 0:
            blocks.append(NarrativeBlock(
                section='efris',
                heading='EFRIS Compliance Report',
                paragraphs=[f"No transactions found for {period_label}."],
            ))
            return blocks

        if rate >= 99:
            status = "fully compliant"
        elif rate >= 95:
            status = "largely compliant with minor gaps"
        elif rate >= 80:
            status = "partially compliant — action required"
        else:
            status = "non-compliant — urgent action required"

        para = (
            f"For {period_label}, a total of {total:,} transactions were processed. "
            f"{fiscalized:,} invoices were successfully submitted to EFRIS "
            f"({rate:.1f}% compliance rate). "
            f"The business is currently {status}. "
            f"{pending:,} transaction(s) remain unsubmitted."
        )

        if store_breakdown:
            worst_store = min(store_breakdown,
                              key=lambda s: _safe_float(s.get('compliance_rate', 100)),
                              default=None)
            if worst_store and _safe_float(worst_store.get('compliance_rate', 100)) < 95:
                para += (
                    f" The store with the lowest compliance is "
                    f"{worst_store.get('store__name', 'Unknown')} at "
                    f"{_safe_float(worst_store.get('compliance_rate')):.1f}%."
                )

        insight = None
        insight_level = 'info'
        if rate < 95:
            insight = (
                f"{pending:,} unsubmitted invoice(s) detected. Failure to fiscalize "
                f"all transactions risks URA penalties. Resolve these immediately."
            )
            insight_level = 'danger' if rate < 80 else 'warning'
        else:
            insight = (
                f"EFRIS compliance is excellent at {rate:.1f}%. Maintain this by "
                f"reviewing the fiscal device status daily."
            )
            insight_level = 'success'

        blocks.append(NarrativeBlock(
            section='efris',
            heading='EFRIS Compliance Report',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class ZReportNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        summary = data.get('summary', {})
        payment_breakdown = data.get('payment_breakdown', [])
        cashier_performance = data.get('cashier_performance', [])
        refunds = data.get('refunds', {})
        voids = data.get('voids', {})

        report_date = data.get('report_date', period_label)
        total_sales = _safe_float(summary.get('total_sales'))
        total_txns = int(summary.get('total_transactions') or 0)
        total_tax = _safe_float(summary.get('total_tax'))
        total_discount = _safe_float(summary.get('total_discount'))
        net_sales = _safe_float(data.get('net_sales'))
        first_time = data.get('first_sale_time', '—')
        last_time = data.get('last_sale_time', '—')
        operating_hours = int(data.get('operating_hours') or 0)

        if total_txns == 0:
            blocks.append(NarrativeBlock(
                section='z_report',
                heading='End of Day — Z Report',
                paragraphs=[
                    f"No sales were recorded on {report_date}. "
                    f"If trading took place, check that the POS system was "
                    f"properly connected and that sales were saved correctly."
                ],
                insight="No transactions found. Verify POS system status.",
                insight_level='warning',
            ))
            return blocks

        para = (
            f"Trading on {report_date} ran from {first_time} to {last_time} "
            f"({operating_hours} hour(s) of operation). "
            f"A total of {total_txns:,} transactions were completed, "
            f"generating {fmt.format(total_sales)} in gross sales. "
            f"After {fmt.format(total_discount)} in discounts and "
            f"{fmt.format(total_tax)} in tax, net sales for the day closed at "
            f"{fmt.format(net_sales)}."
        )

        refund_count = int(refunds.get('count') or 0)
        void_count = int(voids.get('count') or 0)
        if refund_count > 0 or void_count > 0:
            para += (
                f" {refund_count} refund(s) and {void_count} void(s) were "
                f"processed and are reflected in the figures above."
            )

        insight = None
        insight_level = 'info'
        if refund_count > 3:
            refund_amt = _safe_float(refunds.get('amount'))
            insight = (
                f"{refund_count} refunds totalling {fmt.format(refund_amt)} "
                f"were processed today — higher than expected. Investigate "
                f"the reasons for returns."
            )
            insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='z_report',
            heading='End of Day — Z Report',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class ProductPerformanceNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        products = data.get('products', [])
        summary = data.get('summary', {})

        total_products = int(summary.get('total_products') or 0)
        total_qty = int(summary.get('total_quantity_sold') or 0)
        total_rev = _safe_float(summary.get('total_revenue'))

        if total_products == 0:
            blocks.append(NarrativeBlock(
                section='product_performance',
                heading='Product Performance',
                paragraphs=[f"No product sales data was found for {period_label}."],
            ))
            return blocks

        top3 = products[:3]
        top_names = [p.get('product__name', 'Unknown') for p in top3]
        top_rev = _safe_float(top3[0].get('total_revenue')) if top3 else 0

        zero_sales = [p for p in products if _safe_float(p.get('total_revenue')) == 0]

        para = (
            f"During {period_label}, {total_products:,} product(s) recorded sales, "
            f"with {total_qty:,} units sold generating {fmt.format(total_rev)} in "
            f"total revenue. "
            f"The top performer was {top_names[0]} with {fmt.format(top_rev)} in "
            f"sales."
        )
        if len(top_names) > 1:
            para += f" Other strong sellers included {' and '.join(top_names[1:])}."

        insight = None
        insight_level = 'info'
        if zero_sales:
            insight = (
                f"{len(zero_sales)} product(s) recorded zero sales this period. "
                f"Consider reviewing their placement, pricing, or stock availability."
            )
            insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='product_performance',
            heading='Product Performance',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class StockMovementNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        movements = data.get('movements', [])
        summary = data.get('summary', {})

        total_in = _safe_float(summary.get('total_in') or summary.get('total_quantity_in'))
        total_out = _safe_float(summary.get('total_out') or summary.get('total_quantity_out'))
        net = total_in - total_out

        if not movements:
            blocks.append(NarrativeBlock(
                section='stock_movement',
                heading='Stock Movement',
                paragraphs=[f"No stock movement data was found for {period_label}."],
            ))
            return blocks

        direction = "net increase" if net >= 0 else "net decrease"
        para = (
            f"During {period_label}, stock movements recorded {total_in:,.0f} units "
            f"received and {total_out:,.0f} units dispatched or consumed — "
            f"a {direction} of {abs(net):,.0f} units. "
        )

        # Losses flag
        loss_movements = [m for m in movements
                          if str(m.get('movement_type', '')).lower() in
                          ('loss', 'damage', 'wastage', 'write_off')]
        if loss_movements:
            loss_qty = sum(_safe_float(m.get('quantity')) for m in loss_movements)
            para += (
                f"{len(loss_movements)} loss/damage movement(s) totalling "
                f"{loss_qty:,.0f} units were recorded."
            )

        insight = None
        insight_level = 'info'
        if loss_movements:
            insight = (
                f"Stock losses detected ({loss_qty:,.0f} units). Investigate "
                f"causes — damaged goods, theft, or data entry errors."
            )
            insight_level = 'warning'

        blocks.append(NarrativeBlock(
            section='stock_movement',
            heading='Stock Movement Report',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


class CustomerAnalyticsNarrative:
    def build(self, data, prior, delta, fmt, period_label, prior_label,
              reader_role) -> List[NarrativeBlock]:
        blocks = []
        customers = data.get('customers', [])
        summary = data.get('summary', {})

        total_customers = int(summary.get('total_customers') or 0)
        total_rev = _safe_float(summary.get('total_revenue'))
        avg_value = _safe_float(summary.get('avg_customer_value'))
        repeat = int(summary.get('repeat_customers') or 0)

        if total_customers == 0:
            blocks.append(NarrativeBlock(
                section='customer_analytics',
                heading='Customer Analytics',
                paragraphs=[f"No customer transaction data was found for {period_label}."],
            ))
            return blocks

        repeat_pct = (repeat / total_customers * 100) if total_customers > 0 else 0
        top_customer = customers[0] if customers else {}
        top_name = top_customer.get('customer__name', 'Unknown')
        top_spent = _safe_float(top_customer.get('total_spent'))

        para = (
            f"During {period_label}, {total_customers:,} customers made purchases "
            f"totalling {fmt.format(total_rev)}, with an average customer value "
            f"of {fmt.format(avg_value)}. "
            f"{repeat:,} customers ({repeat_pct:.1f}%) made more than one purchase "
            f"— a key indicator of customer loyalty. "
            f"The highest-value customer was {top_name} with "
            f"{fmt.format(top_spent)} in total purchases."
        )

        insight = None
        insight_level = 'info'
        if repeat_pct < 20 and total_customers > 5:
            insight = (
                f"Only {repeat_pct:.0f}% of customers are repeat buyers. "
                f"Consider a loyalty programme or follow-up communication "
                f"to increase retention."
            )
            insight_level = 'warning'
        elif repeat_pct > 50:
            insight = (
                f"Over half of your customers are repeat buyers — excellent "
                f"retention. Maintain this through consistent service quality."
            )
            insight_level = 'success'

        blocks.append(NarrativeBlock(
            section='customer_analytics',
            heading='Customer Analytics',
            paragraphs=[para],
            insight=insight,
            insight_level=insight_level,
        ))

        return blocks


# ── Dispatcher ────────────────────────────────────────────────────────────────

_NARRATOR_MAP = {
    'SALES_SUMMARY': SalesNarrative,
    'PROFIT_LOSS': ProfitNarrative,
    'INVENTORY_STATUS': InventoryNarrative,
    'EXPENSE_REPORT': ExpenseNarrative,
    'EXPENSE_ANALYTICS': ExpenseNarrative,
    'CASHIER_PERFORMANCE': CashierNarrative,
    'TAX_REPORT': TaxNarrative,
    'EFRIS_COMPLIANCE': EFRISNarrative,
    'Z_REPORT': ZReportNarrative,
    'PRODUCT_PERFORMANCE': ProductPerformanceNarrative,
    'STOCK_MOVEMENT': StockMovementNarrative,
    'CUSTOMER_ANALYTICS': CustomerAnalyticsNarrative,
}


def build_narratives(
    report_type: str,
    data: dict,
    prior: dict,
    delta: dict,
    fmt,
    period_label: str,
    prior_label: str,
    reader_role: str = 'owner',
) -> List[NarrativeBlock]:
    """
    Main entry point. Returns a list of NarrativeBlock objects for the
    given report type and data.
    """
    narrator_cls = _NARRATOR_MAP.get(report_type)
    if narrator_cls is None:
        return []
    narrator = narrator_cls()
    try:
        return narrator.build(
            data=data,
            prior=prior,
            delta=delta,
            fmt=fmt,
            period_label=period_label,
            prior_label=prior_label,
            reader_role=reader_role,
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            f"NarrativeEngine: failed to build narrative for {report_type}: {exc}",
            exc_info=True,
        )
        return []


def resolve_reader_role(user) -> str:
    """
    Map a CustomUser's primary_role.priority to a reader role string.
    Priority tiers (from your models):
      >= 90  → owner
      >= 60  → manager
      >= 30  → accountant / auditor
      <  30  → limited
    """
    if user.is_superuser or getattr(user, 'company_admin', False):
        return 'owner'

    primary = getattr(user, 'primary_role', None) or getattr(
        user, 'computed_primary_role', None
    )
    if primary is None:
        return 'limited'

    priority = getattr(primary, 'priority', 0)

    if priority >= 90:
        return 'owner'
    if priority >= 60:
        return 'manager'
    if priority >= 30:
        return 'accountant'
    return 'limited'