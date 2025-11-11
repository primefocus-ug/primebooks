# inventory/test_efris_api.py
# Run with: python manage.py shell < inventory/test_efris_api.py

from company.models import EFRISCommodityCategory

# Check if data exists
total = EFRISCommodityCategory.objects.count()
print(f"Total EFRIS categories: {total}")

# Check leaf nodes
leaf_nodes = EFRISCommodityCategory.objects.filter(is_leaf_node='101').count()
print(f"Leaf nodes: {leaf_nodes}")

# Check products vs services
products = EFRISCommodityCategory.objects.filter(service_mark='101', is_leaf_node='101').count()
services = EFRISCommodityCategory.objects.filter(service_mark='102', is_leaf_node='101').count()
print(f"Product leaf nodes: {products}")
print(f"Service leaf nodes: {services}")

# Test search
results = EFRISCommodityCategory.objects.filter(
    commodity_category_name__icontains='computer',
    is_leaf_node='101'
)[:5]

print("\nSample search results for 'computer':")
for r in results:
    print(f"  {r.commodity_category_code} - {r.commodity_category_name}")