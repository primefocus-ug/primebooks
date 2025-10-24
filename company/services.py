from efris.services import ConfigurationManager, EFRISConfigurationWizard, setup_efris_for_company


class CompanyEFRISService:
    def __init__(self, company):
        self.company = company

    def setup_efris(self):
        """Setup EFRIS for company"""
        return setup_efris_for_company(self.company)

    def get_configuration_status(self):
        """Get EFRIS configuration status"""
        wizard = EFRISConfigurationWizard(self.company)
        return wizard.validate_setup_requirements()