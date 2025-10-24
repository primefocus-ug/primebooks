from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from accounts.models import Role
from company.models import Company
from django_tenants.utils import schema_context

class Command(BaseCommand):
    help = "Ensure each Group has a matching Role entry."

    def handle(self, *args, **options):
        companies = Company.objects.exclude(schema_name='public')

        for company in companies:
            with schema_context(company.schema_name):
                for group in Group.objects.all():
                    role, created = Role.objects.get_or_create(
                        group=group,
                        company=company,
                        defaults={
                            'description': f'Auto-created role for {group.name}',
                            'is_system_role': False,
                            'is_active': True,
                            'color_code': '#6c757d',
                        }
                    )
                    if created:
                        self.stdout.write(f"✓ Created Role for Group: {group.name} in {company.name}")
        self.stdout.write("Role synchronization complete ✅")
