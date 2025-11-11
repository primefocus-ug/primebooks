class Command(BaseCommand):
    help = 'Run automated bank reconciliation'

    def handle(self, *args, **options):
        self.stdout.write("Starting bank reconciliation...")

        results = FinanceAutomation.reconcile_bank_accounts()

        self.stdout.write(self.style.SUCCESS(
            f"Reconciliation complete!\n"
            f"Matched transactions: {len(results['matched'])}\n"
            f"Unmatched bank: {len(results['unmatched_bank'])}\n"
            f"Unmatched book: {len(results['unmatched_book'])}"
        ))