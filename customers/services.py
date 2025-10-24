from efris.services import EFRISCustomerService


class CustomerEFRISService:
    def __init__(self, company):
        self.company = company
        self.efris_service = EFRISCustomerService(company)

    def query_taxpayer(self, tin: str):
        """Query taxpayer by TIN"""
        return self.efris_service.query_taxpayer(tin)

    def enrich_customer(self, customer):
        """Enrich customer from EFRIS"""
        return self.efris_service.enrich_customer_from_efris(customer)

