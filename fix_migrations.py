# fix_sync_migrations.py
# Run this from your project root: python fix_sync_migrations.py

import os
import re

# Map of migration file path -> list of (app_label, ModelName) tuples
MIGRATIONS_TO_FIX = {
    'efris/migrations/0004_sync_ids.py': [
        ('efris', 'CreditNoteApplication'),
        ('efris', 'EFRISApiLog'),
        ('efris', 'EFRISCommodityCategorry'),
        ('efris', 'EFRISConfiguration'),
        ('efris', 'EFRISDeviceInfo'),
        ('efris', 'EFRISDigitalKey'),
        ('efris', 'EFRISErrorPattern'),
        ('efris', 'EFRISExceptionLog'),
        ('efris', 'EFRISFiscalizationBatch'),
        ('efris', 'EFRISIntegrationSettings'),
        ('efris', 'EFRISNotification'),
        ('efris', 'EFRISOperationMetrics'),
        ('efris', 'EFRISSyncQueue'),
        ('efris', 'EFRISSystemDictionary'),
        ('efris', 'FiscalizationAudit'),
        ('efris', 'ProductUploadTask'),
    ],
    # Add other apps below as needed:
    # 'inventory/migrations/0011_sync_ids.py': [
    #     ('inventory', 'Product'),
    #     ...
    # ],
}


TEMPLATE = '''# Auto-fixed by fix_sync_migrations.py
import uuid
from django.db import migrations, models


def populate_sync_ids(apps, schema_editor):
    models_to_update = [
{model_list}
    ]
    for app_label, model_name in models_to_update:
        try:
            Model = apps.get_model(app_label, model_name)
            for obj in Model.objects.filter(sync_id__isnull=True):
                obj.sync_id = uuid.uuid4()
                obj.save(update_fields=['sync_id'])
        except Exception as e:
            print(f"Skipping {{app_label}}.{{model_name}}: {{e}}")


class Migration(migrations.Migration):

    dependencies = [
{dependencies}
    ]

    operations = [
        # STEP 1: Add columns without unique constraint
{step1}

        # STEP 2: Populate unique UUIDs per tenant before index is created
        migrations.RunPython(
            populate_sync_ids,
            migrations.RunPython.noop,
        ),

        # STEP 3: Now safe to add unique constraint
{step3}
    ]
'''


def extract_info_from_migration(filepath):
    """Extract dependencies and model names from existing migration file"""
    with open(filepath, 'r') as f:
        content = f.read()

    # Extract dependencies
    dep_match = re.search(
        r'dependencies\s*=\s*\[(.*?)\]',
        content, re.DOTALL
    )
    dependencies = dep_match.group(1).strip() if dep_match else ''

    # Extract model names from AddField operations
    model_names = re.findall(
        r"migrations\.AddField\(\s*model_name='(\w+)'",
        content
    )

    return dependencies, list(dict.fromkeys(model_names))  # deduplicate


def fix_migration(filepath, app_models):
    """Rewrite a migration file with the three-step pattern"""

    dependencies, _ = extract_info_from_migration(filepath)

    app_label = app_models[0][0]

    # Build model list for populate function
    model_list = '\n'.join(
        f"        ('{a}', '{m}')," for a, m in app_models
    )

    # Get model names in lowercase (as Django migration uses them)
    model_names_lower = [m.lower() for _, m in app_models]

    # Build step 1 - add without unique
    step1_parts = []
    for model_name_lower in model_names_lower:
        step1_parts.append(
            f"        migrations.AddField(\n"
            f"            model_name='{model_name_lower}',\n"
            f"            name='sync_id',\n"
            f"            field=models.UUIDField("
            f"blank=True, null=True, editable=False),\n"
            f"        ),"
        )
    step1 = '\n'.join(step1_parts)

    # Build step 3 - alter to add unique
    step3_parts = []
    for model_name_lower in model_names_lower:
        step3_parts.append(
            f"        migrations.AlterField(\n"
            f"            model_name='{model_name_lower}',\n"
            f"            name='sync_id',\n"
            f"            field=models.UUIDField(\n"
            f"                blank=True, null=True, unique=True,\n"
            f"                db_index=True, default=uuid.uuid4,\n"
            f"                editable=False\n"
            f"            ),\n"
            f"        ),"
        )
    step3 = '\n'.join(step3_parts)

    content = TEMPLATE.format(
        model_list=model_list,
        dependencies=dependencies,
        step1=step1,
        step3=step3,
    )

    with open(filepath, 'w') as f:
        f.write(content)

    print(f"✅ Fixed: {filepath}")


if __name__ == '__main__':
    for filepath, app_models in MIGRATIONS_TO_FIX.items():
        if os.path.exists(filepath):
            fix_migration(filepath, app_models)
            print(f"   Models: {[m for _, m in app_models]}")
        else:
            print(f"❌ File not found: {filepath}")

    print("\nDone! Now run: python manage.py migrate")