# clean_template_sql.py
"""
Clean template SQL for reusability
✅ Removes template-specific data
✅ Keeps only structure
✅ Makes it parameterizable
"""


def clean_template_sql(input_file, output_file):
    """Clean template SQL file"""

    with open(input_file, 'r') as f:
        content = f.read()

    # Remove specific template company data
    lines = content.split('\n')
    cleaned_lines = []
    skip_insert = False

    for line in lines:
        # Skip INSERT statements (we only want structure)
        if line.strip().startswith('INSERT INTO'):
            skip_insert = True
        elif skip_insert and line.strip().endswith(');'):
            skip_insert = False
            continue
        elif skip_insert:
            continue

        # Keep CREATE TABLE, ALTER TABLE, CREATE INDEX
        if any(line.strip().startswith(cmd) for cmd in [
            'CREATE TABLE',
            'ALTER TABLE',
            'CREATE INDEX',
            'CREATE SEQUENCE',
            'ALTER SEQUENCE'
        ]):
            cleaned_lines.append(line)
        elif line.strip().startswith(('SET ', 'SELECT ', 'CREATE SCHEMA')):
            cleaned_lines.append(line)
        elif not line.strip():
            cleaned_lines.append(line)

    # Write cleaned content
    with open(output_file, 'w') as f:
        f.write('\n'.join(cleaned_lines))

    print(f"✅ Cleaned SQL saved to {output_file}")


# Run it
clean_template_sql('primebooks_tenant_raw.sql', 'primebooks_tenant.sql')