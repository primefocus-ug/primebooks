from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from accounts.models import Role
from company.models import Company
from django_tenants.utils import schema_context
from django.db import transaction
from django.conf import settings


class Command(BaseCommand):
    help = "Ensure each Group has a matching Role entry across all tenants"

    def add_arguments(self, parser):
        parser.add_argument(
            '--company',
            type=str,
            help='Specific company ID to sync roles for (default: all companies)',
        )
        parser.add_argument(
            '--create-default-roles',
            action='store_true',
            help='Create default system roles if they dont exist',
        )
        parser.add_argument(
            '--fix-priorities',
            action='store_true',
            help='Fix role priorities based on role names',
        )
        parser.add_argument(
            '--list-roles',
            action='store_true',
            help='List all roles across companies',
        )
        parser.add_argument(
            '--update-existing',
            action='store_true',
            help='Update existing roles with new defaults',
        )

    def handle(self, *args, **options):
        company_id = options.get('company')
        create_default_roles = options.get('create_default_roles')
        fix_priorities = options.get('fix_priorities')
        list_roles = options.get('list_roles')
        update_existing = options.get('update_existing')

        if company_id:
            companies = Company.objects.filter(company_id=company_id)
        else:
            companies = Company.objects.exclude(schema_name='public')

        if list_roles:
            self.list_all_roles(companies)
            return

        total_created = 0
        total_updated = 0

        for company in companies:
            with schema_context(company.schema_name):
                company_created, company_updated = self.sync_roles_for_company(
                    company, create_default_roles, fix_priorities, update_existing
                )
                total_created += company_created
                total_updated += company_updated

        self.stdout.write(
            self.style.SUCCESS(
                f"Role synchronization complete! Created: {total_created}, Updated: {total_updated} ✅"
            )
        )

    def sync_roles_for_company(self, company, create_default_roles=False, fix_priorities=False, update_existing=False):
        """Sync roles for a specific company"""
        created_count = 0
        updated_count = 0

        # Create default system roles if requested
        if create_default_roles:
            default_created = self.create_default_system_roles(company)
            created_count += default_created

        # Sync existing groups with roles
        for group in Group.objects.all():
            try:
                # Try to get existing role first
                role = Role.objects.get(group=group, company=company)

                # Update existing role if needed
                if update_existing or fix_priorities:
                    updated = self._update_role_if_needed(role, group.name, fix_priorities)
                    if updated:
                        updated_count += 1

            except Role.DoesNotExist:
                # Create new role if it doesn't exist
                role = self._create_role_for_group(group, company)
                if role:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ Created Role for Group: {group.name} in {company.name}"
                        )
                    )

        return created_count, updated_count

    def _create_role_for_group(self, group, company):
        """Create a new role for a group"""
        try:
            role = Role.objects.create(
                group=group,
                company=company,
                description=f'Auto-created role for {group.name}',
                is_system_role=self._is_system_role(group.name),
                is_active=True,
                priority=self._get_default_priority(group.name),
                color_code=self._get_default_color(group.name),
            )
            return role
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f"✗ Failed to create role for {group.name} in {company.name}: {str(e)}"
                )
            )
            return None

    def create_default_system_roles(self, company):
        """Create default system roles for a company"""
        default_roles = [
            {
                'name': 'System Administrator',
                'description': 'Full system access with superuser privileges',
                'priority': 100,
                'color_code': '#dc3545',
                'is_system_role': True,
            },
            {
                'name': 'Company Administrator',
                'description': 'Company-level administrative access',
                'priority': 90,
                'color_code': '#fd7e14',
                'is_system_role': True,
            },
            {
                'name': 'Operations Manager',
                'description': 'Operations and team management access',
                'priority': 80,
                'color_code': '#20c997',
                'is_system_role': True,
            },
            {
                'name': 'Store Manager',
                'description': 'Store management and reporting access',
                'priority': 70,
                'color_code': '#0dcaf0',
                'is_system_role': False,
            },
            {
                'name': 'Cashier',
                'description': 'Point of sale and transaction processing',
                'priority': 60,
                'color_code': '#6f42c1',
                'is_system_role': False,
            },
            {
                'name': 'Inventory Manager',
                'description': 'Inventory and stock management access',
                'priority': 65,
                'color_code': '#d63384',
                'is_system_role': False,
            },
            {
                'name': 'Sales Associate',
                'description': 'Basic sales and customer service access',
                'priority': 50,
                'color_code': '#6c757d',
                'is_system_role': False,
            },
            {
                'name': 'View Only',
                'description': 'Read-only access for reporting and analytics',
                'priority': 30,
                'color_code': '#adb5bd',
                'is_system_role': False,
            },
        ]

        created_count = 0
        for role_config in default_roles:
            try:
                group, group_created = Group.objects.get_or_create(name=role_config['name'])

                # Check if role already exists
                if not Role.objects.filter(group=group, company=company).exists():
                    role = Role.objects.create(
                        group=group,
                        company=company,
                        description=role_config['description'],
                        is_system_role=role_config['is_system_role'],
                        is_active=True,
                        priority=role_config['priority'],
                        color_code=role_config['color_code'],
                    )
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ Created default role: {role_config['name']} in {company.name}"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"⏭️  Default role already exists: {role_config['name']} in {company.name}"
                        )
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"✗ Failed to create default role {role_config['name']}: {str(e)}"
                    )
                )

        return created_count

    def _is_system_role(self, group_name):
        """Determine if a group should be a system role"""
        system_role_keywords = [
            'admin', 'administrator', 'system', 'superuser', 'super',
            'owner', 'manager', 'director'
        ]
        return any(keyword in group_name.lower() for keyword in system_role_keywords)

    def _get_default_priority(self, group_name):
        """Get default priority based on role name"""
        name_lower = group_name.lower()

        priority_mapping = {
            'system administrator': 100,
            'superuser': 100,
            'super admin': 100,
            'company administrator': 90,
            'company admin': 90,
            'owner': 90,
            'director': 85,
            'operations manager': 80,
            'store manager': 70,
            'inventory manager': 65,
            'cashier': 60,
            'sales associate': 50,
            'user': 40,
            'view only': 30,
            'guest': 20,
        }

        # Check for exact matches first
        for key, priority in priority_mapping.items():
            if key in name_lower:
                return priority

        # Fallback based on keywords
        if any(word in name_lower for word in ['admin', 'administrator']):
            return 90
        elif any(word in name_lower for word in ['manager', 'director']):
            return 80
        elif any(word in name_lower for word in ['supervisor', 'lead']):
            return 70
        elif any(word in name_lower for word in ['cashier', 'sales']):
            return 60
        elif any(word in name_lower for word in ['user', 'member']):
            return 50
        elif any(word in name_lower for word in ['view', 'readonly']):
            return 30
        else:
            return 50  # Default priority

    def _get_default_color(self, group_name):
        """Get default color based on role name"""
        name_lower = group_name.lower()

        color_mapping = {
            'system administrator': '#dc3545',  # Red
            'superuser': '#dc3545',
            'company administrator': '#fd7e14',  # Orange
            'company admin': '#fd7e14',
            'owner': '#fd7e14',
            'director': '#ffc107',  # Yellow
            'operations manager': '#20c997',  # Teal
            'store manager': '#0dcaf0',  # Cyan
            'inventory manager': '#d63384',  # Pink
            'cashier': '#6f42c1',  # Purple
            'sales associate': '#6c757d',  # Gray
            'user': '#6c757d',
            'view only': '#adb5bd',  # Light gray
            'guest': '#dee2e6',  # Very light gray
        }

        # Check for exact matches
        for key, color in color_mapping.items():
            if key in name_lower:
                return color

        # Fallback colors based on role type
        if any(word in name_lower for word in ['admin', 'administrator']):
            return '#fd7e14'  # Orange
        elif any(word in name_lower for word in ['manager', 'director']):
            return '#20c997'  # Teal
        elif any(word in name_lower for word in ['supervisor', 'lead']):
            return '#0dcaf0'  # Cyan
        elif any(word in name_lower for word in ['cashier', 'sales']):
            return '#6f42c1'  # Purple
        else:
            return '#6c757d'  # Default gray

    def _update_role_if_needed(self, role, group_name, fix_priorities=False):
        """Update role properties if they need correction"""
        updated = False

        # Fix priority if requested or if it's 0
        if fix_priorities or role.priority == 0:
            new_priority = self._get_default_priority(group_name)
            if role.priority != new_priority:
                role.priority = new_priority
                updated = True
                self.stdout.write(
                    self.style.WARNING(
                        f"↻ Updated priority for {group_name}: {role.priority} → {new_priority}"
                    )
                )

        # Ensure system role flag is correct
        should_be_system = self._is_system_role(group_name)
        if role.is_system_role != should_be_system:
            role.is_system_role = should_be_system
            updated = True
            self.stdout.write(
                self.style.WARNING(
                    f"↻ Updated system role flag for {group_name}: {role.is_system_role} → {should_be_system}"
                )
            )

        # Ensure role is active
        if not role.is_active:
            role.is_active = True
            updated = True
            self.stdout.write(
                self.style.WARNING(
                    f"↻ Activated role: {group_name}"
                )
            )

        # Update description if it's the default one
        default_description = f'Auto-created role for {group_name}'
        if role.description == default_description:
            new_description = self._get_role_description(group_name)
            if new_description != default_description:
                role.description = new_description
                updated = True

        if updated:
            role.save()

        return updated

    def _get_role_description(self, group_name):
        """Get a better description for common roles"""
        description_mapping = {
            'system administrator': 'Full system access with superuser privileges',
            'company administrator': 'Company-level administrative access',
            'operations manager': 'Operations and team management access',
            'store manager': 'Store management and reporting access',
            'cashier': 'Point of sale and transaction processing',
            'inventory manager': 'Inventory and stock management access',
            'sales associate': 'Basic sales and customer service access',
            'view only': 'Read-only access for reporting and analytics',
        }

        name_lower = group_name.lower()
        for key, description in description_mapping.items():
            if key in name_lower:
                return description

        return f'Auto-created role for {group_name}'

    def list_all_roles(self, companies):
        """List all roles across companies"""
        total_roles = 0

        for company in companies:
            with schema_context(company.schema_name):
                roles = Role.objects.select_related('group').order_by('-priority', 'group__name')
                role_count = roles.count()
                total_roles += role_count

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n🏢 {company.name} ({company.schema_name}) - {role_count} roles:"
                    )
                )

                for role in roles:
                    status = "🟢" if role.is_active else "🔴"
                    system = "⚙️" if role.is_system_role else "👥"
                    self.stdout.write(
                        f"  {status} {system} {role.group.name:<25} "
                        f"Priority: {role.priority:<3} "
                        f"Users: {role.user_count:<3} "
                        f"Color: {role.color_code}"
                    )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n📊 Total: {total_roles} roles across {companies.count()} companies"
            )
        )

    def cleanup_orphaned_roles(self, company):
        """Clean up roles that don't have associated groups"""
        with schema_context(company.schema_name):
            # Find roles where the group no longer exists
            orphaned_roles = Role.objects.filter(
                company=company
            ).exclude(
                group__in=Group.objects.all()
            )

            count = orphaned_roles.count()
            if count > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"🗑️  Removing {count} orphaned roles from {company.name}"
                    )
                )
                orphaned_roles.delete()

            return count