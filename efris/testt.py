from .services import EFRISClient

# Initialize client
client = EFRISClient(
    tin="YOUR_TIN",
    device_no="YOUR_DEVICE_NO",
    private_key_path="path/to/privateKey.pem",
    public_cert_path="path/to/publicCert.pem",
    aes_key_path="path/to/aes_key.txt"
)

try:
    # 1. Query stock for a product
    print("=== Querying Stock ===")
    stock_info = client.t128_query_stock_by_goods_id("290707933831281139")
    print(f"Current stock: {stock_info.get('stock', 'N/A')}")
    print(f"Stock warning: {stock_info.get('stockPrewarning', 'N/A')}")
    print()

    # 2. Increase inventory (Local Purchase)
    print("=== Increasing Inventory ===")
    items = [{
        "goodsCode": "PROD001",
        "measureUnit": "101",
        "quantity": "100.00",
        "unitPrice": "5000.00"
    }]
    result = client.increase_stock(
        items=items,
        stock_in_type="102",  # Local Purchase
        supplier_name="ABC Suppliers",
        supplier_tin="1234567890",
        stock_in_date="2025-01-15"
    )
    print("Increase stock result:", result)
    print()

    # 3. Decrease inventory (Damaged goods)
    print("=== Decreasing Inventory ===")
    result = client.decrease_stock(
        items=[{
            "goodsCode": "PROD001",
            "measureUnit": "101",
            "quantity": "10.00",
            "unitPrice": "5000.00"
        }],
        adjust_type="102",  # Damaged
        remarks="Water damage"
    )
    print("Decrease stock result:", result)
    print()

    # 4. Transfer stock between branches
    print("=== Transferring Stock ===")
    result = client.t139_transfer_stock(
        source_branch_id="206637525568955296",
        destination_branch_id="206637528324276772",
        transfer_type_code="101",
        transfer_items=[{
            "goodsCode": "PROD001",
            "measureUnit": "101",
            "quantity": "50.00"
        }]
    )
    print("Transfer result:", result)
    print()

    # 5. Query stock records
    print("=== Querying Stock Records ===")
    records = client.t147_query_stock_records_advanced(
        start_date="2025-01-01",
        end_date="2025-01-31",
        stock_in_type="102",
        page_no="1",
        page_size="10"
    )
    print(f"Total records: {records.get('page', {}).get('totalSize', 0)}")
    print(f"Records found: {len(records.get('records', []))}")
    print()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()