#!/bin/bash
#
# Setup Script - Schema Loader
# Makes scripts executable and verifies setup
#

echo
"╔════════════════════════════════════════════════════════════════╗"
echo
"║  Schema Loader - Setup Script"
echo
"╚════════════════════════════════════════════════════════════════╝"
echo
""

# Colors for output
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
NC = '\033[0m'  # No Color

# Track success/failure
WARNINGS = 0
ERRORS = 0

# Function to check if command exists
command_exists()
{
    command - v
"$1" & > / dev / null
}

echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
"Step 1: Checking Prerequisites"
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
""

# Check for pg_dump
if command_exists pg_dump; then
PG_VERSION =$(pg_dump - -version | head - n1)
echo - e
"${GREEN}✓${NC} pg_dump found: $PG_VERSION"
else
echo - e
"${RED}✗${NC} pg_dump not found"
echo
"  Install PostgreSQL client tools:"
echo
"  Ubuntu/Debian: sudo apt-get install postgresql-client"
echo
"  macOS: brew install postgresql"
ERRORS =$((ERRORS + 1))
fi

# Check for psql
if command_exists psql; then
echo - e
"${GREEN}✓${NC} psql found"
else
echo - e
"${YELLOW}⚠${NC} psql not found (optional, but recommended)"
WARNINGS =$((WARNINGS + 1))
fi

# Check for Python
if command_exists python3; then
PYTHON_VERSION =$(python3 - -version)
echo - e
"${GREEN}✓${NC} Python found: $PYTHON_VERSION"
else
echo - e
"${RED}✗${NC} Python 3 not found"
ERRORS =$((ERRORS + 1))
fi

echo
""

# Check database connection
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
"Step 2: Checking Database Connection"
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
""

if command_exists psql; then
if psql - h localhost -U postgres -d data -c "SELECT version();" & > / dev / null; then
echo - e
"${GREEN}✓${NC} Connected to database 'data'"
else
echo - e
"${YELLOW}⚠${NC} Cannot connect to database 'data'"
echo
"  Make sure PostgreSQL is running and credentials are correct"
WARNINGS =$((WARNINGS + 1))
fi
else
echo - e
"${YELLOW}⚠${NC} Skipping database check (psql not found)"
WARNINGS =$((WARNINGS + 1))
fi

echo
""

# Make scripts executable
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
"Step 3: Making Scripts Executable"
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
""

SCRIPTS = (
    "export_all_schemas.sh"
    "export_public_schema.sh"
    "export_tenant_schema.sh"
)

for script in "${SCRIPTS[@]}"; do
if [-f "$script"]; then
chmod + x
"$script"
echo - e
"${GREEN}✓${NC} Made executable: $script"
else
echo - e
"${RED}✗${NC} File not found: $script"
ERRORS =$((ERRORS + 1))
fi
done

echo
""

# Check Python files
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
"Step 4: Verifying Python Files"
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
""

PYTHON_FILES = (
    "schema_loader.py"
    "example_usage.py"
)

for file in "${PYTHON_FILES[@]}"; do
if [-f "$file"]; then
echo - e
"${GREEN}✓${NC} Found: $file"

# Check syntax
if command_exists python3; then
if python3 - m py_compile "$file" 2 > / dev / null; then
echo - e
"${GREEN}✓${NC} Syntax OK: $file"
else
echo - e
"${RED}✗${NC} Syntax error in: $file"
ERRORS =$((ERRORS + 1))
fi
fi
else
echo - e
"${RED}✗${NC} File not found: $file"
ERRORS =$((ERRORS + 1))
fi
done

echo
""

# Check documentation
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
"Step 5: Verifying Documentation"
echo
"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
""

DOCS = (
    "README.md"
    "QUICK_REFERENCE.md"
)

for doc in "${DOCS[@]}"; do
if [-f "$doc"]; then
echo - e
"${GREEN}✓${NC} Found: $doc"
else
echo - e
"${YELLOW}⚠${NC} Missing: $doc"
WARNINGS =$((WARNINGS + 1))
fi
done

echo
""

# Summary
echo
"╔════════════════════════════════════════════════════════════════╗"
echo
"║  Setup Summary"
echo
"╚════════════════════════════════════════════════════════════════╝"
echo
""

if [ $ERRORS -eq 0] & &[$WARNINGS -eq 0]; then
echo - e
"${GREEN}✓ Setup completed successfully!${NC}"
echo
""
echo
"Next steps:"
echo
"  1. Export your schemas:"
echo
"     ./export_all_schemas.sh"
echo
""
echo
"  2. Try the examples:"
echo
"     python3 example_usage.py"
echo
""
echo
"  3. Read the docs:"
echo
"     cat README.md"
echo
"     cat QUICK_REFERENCE.md"
echo
""
elif [ $ERRORS - eq
0]; then
echo - e
"${YELLOW}⚠ Setup completed with warnings${NC}"
echo
""
echo
"Warnings: $WARNINGS"
echo
""
echo
"You can proceed, but some features may not work."
echo
"Review the warnings above and fix them if needed."
echo
""
else
echo - e
"${RED}✗ Setup completed with errors${NC}"
echo
""
echo
"Errors: $ERRORS"
echo
"Warnings: $WARNINGS"
echo
""
echo
"Please fix the errors above before proceeding."
echo
""
exit
1
fi

# Show file structure
echo
"File structure:"
echo
"  📄 schema_loader.py        - Main loader module"
echo
"  📄 example_usage.py         - Usage examples"
echo
"  📄 export_all_schemas.sh    - Export both schemas"
echo
"  📄 export_public_schema.sh  - Export public only"
echo
"  📄 export_tenant_schema.sh  - Export tenant only"
echo
"  📄 README.md                - Full documentation"
echo
"  📄 QUICK_REFERENCE.md       - Quick reference guide"
echo
""

echo
"╔════════════════════════════════════════════════════════════════╗"
echo
"║  Ready to use! 🚀"
echo
"╚════════════════════════════════════════════════════════════════╝"