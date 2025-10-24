# management/commands/bulk_import.py
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.db import transaction
import os
import json
from ...models import ImportSession
from ...views import process_import_file

class Command(BaseCommand):
    help = 'Import stock data from CSV or Excel file via command line'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to the import file')
        parser.add_argument('--user', type=str, required=True, help='Username of the user performing the import')
        parser.add_argument('--mode', type=str, default='both', 
                          choices=['add', 'update', 'both'], 
                          help='Import mode: add, update, or both')
        parser.add_argument('--conflict', type=str, default='overwrite',
                          choices=['skip', 'overwrite', 'merge'],
                          help='Conflict resolution strategy')
        parser.add_argument('--mapping', type=str, 
                          help='JSON string containing column mapping')
        parser.add_argument('--header', action='store_true', default=True,
                          help='File has header row')
        parser.add_argument('--no-header', dest='header', action='store_false',
                          help='File does not have header row')
        parser.add_argument('--dry-run', action='store_true',
                          help='Perform a dry run without saving data')
        parser.add_argument('--batch-size', type=int, default=1000,
                          help='Number of records to process in each batch')

    def handle(self, *args, **options):
        file_path = options['file_path']
        username = options['user']
        import_mode = options['mode']
        conflict_resolution = options['conflict']
        has_header = options['header']
        dry_run = options['dry_run']
        batch_size = options['batch_size']

        # Validate file exists
        if not os.path.exists(file_path):
            raise CommandError(f'File "{file_path}" does not exist.')

        # Validate user exists
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist.')

        # Parse column mapping if provided
        column_mapping = {}
        if options['mapping']:
            try:
                column_mapping = json.loads(options['mapping'])
            except json.JSONDecodeError:
                raise CommandError('Invalid JSON format for column mapping.')

        # Default column mapping if none provided
        if not column_mapping:
            column_mapping = {
                'product_name': '0',
                'sku': '1', 
                'quantity': '2',
                'store': '3'
            }
            self.stdout.write(
                self.style.WARNING(
                    'No column mapping provided. Using default mapping:\n'
                    f'{json.dumps(column_mapping, indent=2)}'
                )
            )

        self.stdout.write(f'Starting import from: {file_path}')
        self.stdout.write(f'User: {username}')
        self.stdout.write(f'Mode: {import_mode}')
        self.stdout.write(f'Conflict resolution: {conflict_resolution}')
        self.stdout.write(f'Has header: {has_header}')
        self.stdout.write(f'Dry run: {dry_run}')
        self.stdout.write('-' * 50)

        try:
            # Create a file-like object for the import function
            class FileWrapper:
                def __init__(self, file_path):
                    self.file_path = file_path
                    self.name = os.path.basename(file_path)
                    self.size = os.path.getsize(file_path)
                
                def read(self):
                    with open(self.file_path, 'rb') as f:
                        return f.read()
                
                def seek(self, pos):
                    pass  # Not needed for our use case

            file_wrapper = FileWrapper(file_path)
            
            if dry_run:
                self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be saved'))
                # For dry run, we'll analyze the file but not save anything
                result = self.analyze_file_only(file_wrapper, column_mapping, has_header)
            else:
                # Process the import
                result = process_import_file(
                    file_wrapper,
                    import_mode,
                    conflict_resolution,
                    column_mapping,
                    has_header,
                    user
                )

            # Display results
            self.display_results(result, dry_run)

        except Exception as e:
            raise CommandError(f'Import failed: {str(e)}')

    def analyze_file_only(self, file, column_mapping, has_header):
        """Analyze file without importing - for dry run"""
        from ...views import read_csv_data, read_excel_data, map_row_data, validate_row_data
        
        # Read file data
        if file.name.lower().endswith('.csv'):
            data = read_csv_data(file, has_header)
        else:
            data = read_excel_data(file, has_header)

        results = {
            'success': True,
            'total_processed': len(data),
            'created': [],
            'updated': [],
            'skipped': [],
            'errors': [],
            'summary': {
                'created_count': 0,
                'updated_count': 0,
                'skipped_count': 0,
                'error_count': 0
            }
        }

        # Analyze each row
        for row_index, row_data in enumerate(data):
            try:
                # Map columns
                mapped_data = map_row_data(row_data, column_mapping)
                
                # Validate
                if validate_row_data(mapped_data):
                    # For dry run, assume all valid rows would be created
                    results['created'].append({
                        'product': mapped_data.get('product_name', 'Unknown'),
                        'store': mapped_data.get('store', 'Unknown'),
                        'quantity': mapped_data.get('quantity', '0')
                    })
                    results['summary']['created_count'] += 1
                else:
                    results['errors'].append({
                        'row': row_index + (2 if has_header else 1),
                        'error': 'Missing required fields',
                        'details': str(mapped_data)
                    })
                    results['summary']['error_count'] += 1
                    
            except Exception as e:
                results['errors'].append({
                    'row': row_index + (2 if has_header else 1),
                    'error': str(e),
                    'details': str(row_data)
                })
                results['summary']['error_count'] += 1

        return results

    def display_results(self, result, dry_run=False):
        """Display import results in a formatted way"""
        if not result['success']:
            self.stdout.write(
                self.style.ERROR(f'Import failed: {result.get("error", "Unknown error")}')
            )
            return

        summary = result['summary']
        
        # Summary statistics
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS('IMPORT SUMMARY'))
        self.stdout.write('=' * 50)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN RESULTS:'))
        
        self.stdout.write(f'Total rows processed: {result["total_processed"]}')
        self.stdout.write(self.style.SUCCESS(f'Would create: {summary["created_count"]} items'))
        self.stdout.write(self.style.SUCCESS(f'Would update: {summary["updated_count"]} items'))
        
        if summary['skipped_count'] > 0:
            self.stdout.write(self.style.WARNING(f'Would skip: {summary["skipped_count"]} items'))
        
        if summary['error_count'] > 0:
            self.stdout.write(self.style.ERROR(f'Errors: {summary["error_count"]} items'))

        # Show sample created items
        if result['created'][:5]:  # Show first 5
            self.stdout.write('\nSample items that would be created:')
            for item in result['created'][:5]:
                self.stdout.write(f'  - {item["product"]} at {item["store"]}: {item["quantity"]}')
            
            if len(result['created']) > 5:
                self.stdout.write(f'  ... and {len(result["created"]) - 5} more')

        # Show sample errors
        if result['errors'][:5]:  # Show first 5 errors
            self.stdout.write('\nSample errors:')
            for error in result['errors'][:5]:
                self.stdout.write(
                    self.style.ERROR(f'  Row {error["row"]}: {error["error"]}')
                )
            
            if len(result['errors']) > 5:
                self.stdout.write(f'  ... and {len(result["errors"]) - 5} more errors')

        # Success rate
        if result['total_processed'] > 0:
            success_count = summary['created_count'] + summary['updated_count']
            success_rate = (success_count / result['total_processed']) * 100
            
            if success_rate >= 90:
                style = self.style.SUCCESS
            elif success_rate >= 70:
                style = self.style.WARNING
            else:
                style = self.style.ERROR
                
            self.stdout.write(f'\nSuccess rate: {style(f"{success_rate:.1f}%")}')

        if not dry_run and result['success']:
            self.stdout.write('\n' + self.style.SUCCESS('Import completed successfully!'))
        elif dry_run:
            self.stdout.write('\n' + self.style.WARNING('Dry run completed. Use without --dry-run to perform actual import.'))

# Example usage comment:
"""
Usage examples:

# Basic import with default mapping
python manage.py bulk_import /path/to/file.csv --user admin

# Import with custom column mapping
python manage.py bulk_import /path/to/file.xlsx --user admin --mapping '{"product_name": "0", "sku": "1", "quantity": "2", "store": "3"}'

# Dry run to test before importing
python manage.py bulk_import /path/to/file.csv --user admin --dry-run

# Import with specific settings
python manage.py bulk_import /path/to/file.csv --user admin --mode update --conflict merge --no-header

# Large file import with custom batch size
python manage.py bulk_import /path/to/large_file.csv --user admin --batch-size 5000
"""