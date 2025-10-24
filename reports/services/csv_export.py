"""
CSV Export Service
"""
import csv
from io import StringIO, BytesIO
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class CSVExportService:
    """Professional CSV export service"""

    def __init__(self, report_data: Dict[str, Any], report_name: str):
        self.report_data = report_data
        self.report_name = report_name

    def generate_csv(self) -> BytesIO:
        """Generate CSV file"""
        output = StringIO()

        # Determine which data to export
        if 'grouped_data' in self.report_data and self.report_data['grouped_data']:
            self._write_data_to_csv(output, self.report_data['grouped_data'])
        elif 'products' in self.report_data and self.report_data['products']:
            self._write_data_to_csv(output, self.report_data['products'])
        elif 'inventory' in self.report_data and self.report_data['inventory']:
            self._write_data_to_csv(output, self.report_data['inventory'])
        else:
            # Export summary if no detailed data
            if 'summary' in self.report_data:
                self._write_summary_to_csv(output, self.report_data['summary'])

        # Convert to BytesIO
        buffer = BytesIO()
        buffer.write(output.getvalue().encode('utf-8-sig'))  # UTF-8 with BOM for Excel
        buffer.seek(0)

        return buffer

    def _write_data_to_csv(self, output: StringIO, data: List[Dict]):
        """Write list of dictionaries to CSV"""
        if not data:
            return

        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()

        for row in data:
            # Convert values to strings
            cleaned_row = {k: self._format_value(v) for k, v in row.items()}
            writer.writerow(cleaned_row)

    def _write_summary_to_csv(self, output: StringIO, summary: Dict):
        """Write summary data to CSV"""
        writer = csv.writer(output)
        writer.writerow(['Metric', 'Value'])

        for key, value in summary.items():
            formatted_key = key.replace('_', ' ').title()
            formatted_value = self._format_value(value)
            writer.writerow([formatted_key, formatted_value])

    def _format_value(self, value):
        """Format value for CSV export"""
        if value is None:
            return ''
        elif isinstance(value, float):
            return f"{value:.2f}"
        elif isinstance(value, (list, dict)):
            return str(value)
        else:
            return str(value)

