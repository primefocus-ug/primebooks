"""
EFRIS Complete Test Runner
Run this script to diagnose and fix your EFRIS integration issues

Usage:
    python manage.py shell
     from efris.test_runner import run_all_tests
    run_all_tests('primefocus')  # Your schema name
"""

from django_tenants.utils import schema_context
import json
import base64


def run_all_tests(schema_name):
    """Run all EFRIS tests in sequence"""
    print("\n" + "=" * 100)
    print("EFRIS COMPLETE DIAGNOSTIC TEST SUITE")
    print("=" * 100)

    with schema_context(schema_name):
        from company.models import Company
        from inventory.models import Product
        from invoices.models import Invoice

        company = Company.objects.first()

        if not company:
            print("❌ No company found in schema")
            return

        print(f"\nCompany: {company.name}")
        print(f"TIN: {company.tin}")
        print(f"Schema: {schema_name}")

        # Test 1: Configuration
        print("\n" + "=" * 100)
        test_configuration(company)

        # Test 2: Encryption
        print("\n" + "=" * 100)
        test_encryption(company)

        # Test 3: Product Data
        print("\n" + "=" * 100)
        test_product_data(company)

        # Test 4: Invoice Data
        print("\n" + "=" * 100)
        test_invoice_data(company)

        # Test 5: Live API Test
        print("\n" + "=" * 100)
        test_live_api(company)

        print("\n" + "=" * 100)
        print("TEST SUITE COMPLETE")
        print("=" * 100)


def test_configuration(company):
    """Test 1: Configuration Check"""
    print("TEST 1: EFRIS CONFIGURATION")
    print("-" * 100)

    issues = []

    # Check basic config
    if not hasattr(company, 'efris_config'):
        issues.append("No EFRIS configuration found")
        print("❌ CRITICAL: No EFRIS configuration")
        return False

    config = company.efris_config

    # Check private key
    if not config.private_key:
        issues.append("Private key missing")
        print("❌ Private key: MISSING")
    else:
        print("✅ Private key: Present")
        try:
            from cryptography.hazmat.primitives import serialization
            serialization.load_pem_private_key(
                config.private_key.encode('utf-8'),
                password=config.key_password.encode('utf-8') if config.key_password else None
            )
            print("✅ Private key: Valid")
        except Exception as e:
            issues.append(f"Private key invalid: {e}")
            print(f"❌ Private key: Invalid - {e}")

    # Check public certificate
    if not config.public_certificate:
        issues.append("Public certificate missing")
        print("❌ Public certificate: MISSING")
    else:
        print("✅ Public certificate: Present")

    # Check device number
    if not config.device_number:
        issues.append("Device number missing")
        print("❌ Device number: MISSING")
    else:
        print(f"✅ Device number: {config.device_number}")

    # Check company info
    required_fields = ['tin', 'efris_taxpayer_name', 'efris_business_name',
                       'efris_email_address', 'efris_phone_number']

    for field in required_fields:
        value = getattr(company, field, None)
        if not value:
            issues.append(f"Company {field} missing")
            print(f"❌ {field}: MISSING")
        else:
            print(f"✅ {field}: {value}")

    if issues:
        print(f"\n❌ Configuration has {len(issues)} issues")
        return False
    else:
        print("\n✅ Configuration is complete")
        return True


def test_encryption(company):
    """Test 2: Encryption Process"""
    print("TEST 2: ENCRYPTION PROCESS")
    print("-" * 100)

    from efris.services import EnhancedEFRISAPIClient

    try:
        client = EnhancedEFRISAPIClient(company)

        # Step 1: Get AES key
        print("\nStep 1: Getting AES key (T104)...")
        auth_result = client.ensure_authenticated()

        if not auth_result.get("success"):
            print(f"❌ Authentication failed: {auth_result.get('error')}")
            return False

        aes_key = client.security_manager.get_current_aes_key()
        if not aes_key:
            print("❌ No AES key available")
            return False

        print(f"✅ AES key obtained: {len(aes_key)} bytes")
        print(f"   Key (hex first 32 chars): {aes_key.hex()[:32]}...")

        # Step 2: Test encryption/decryption
        print("\nStep 2: Testing AES encryption/decryption...")
        test_data = {"test": "value", "number": 123}
        test_json = json.dumps(test_data, separators=(',', ':'), ensure_ascii=False)

        try:
            encrypted = client.security_manager.encrypt_with_aes(test_json, aes_key)
            print(f"✅ Encryption successful: {len(encrypted)} chars")

            decrypted = client.security_manager.decrypt_with_aes(encrypted, aes_key)

            if decrypted == test_json:
                print("✅ Decryption successful: Content matches")
            else:
                print("❌ Decryption mismatch!")
                print(f"   Original: {test_json}")
                print(f"   Decrypted: {decrypted}")
                return False

        except Exception as e:
            print(f"❌ Encryption/Decryption failed: {e}")
            return False

        # Step 3: Test signature
        print("\nStep 3: Testing RSA signature...")
        try:
            private_key = client._load_private_key()
            signature = client.security_manager.sign_content(test_json, private_key)
            print(f"✅ Signature generated: {len(signature)} chars")
            print(f"   Signature (first 50): {signature[:50]}...")
        except Exception as e:
            print(f"❌ Signature generation failed: {e}")
            return False

        print("\n✅ Encryption process working correctly")
        return True

    except Exception as e:
        print(f"❌ Encryption test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_product_data(company):
    """Test 3: Product Data Structure"""
    print("TEST 3: PRODUCT DATA STRUCTURE (T130)")
    print("-" * 100)

    from inventory.models import Product

    product = Product.objects.filter(is_active=True).first()

    if not product:
        print("⚠️  No active products found - skipping test")
        return None

    print(f"\nTesting product: {product.name}")
    print(f"ID: {product.id}, SKU: {getattr(product, 'sku', 'N/A')}")

    # Build T130 data
    goods_data = {
        "operationType": "101",
        "goodsName": str(product.name[:200]),
        "goodsCode": str(getattr(product, 'sku', f'PROD{product.id}')),
        "measureUnit": "101",  # From T115
        "unitPrice": f"{float(getattr(product, 'selling_price', 0)):.2f}",
        "currency": "101",  # UGX
        "commodityCategoryId": str(getattr(product, 'efris_commodity_category_id', None) or '1010101000'),
        "haveExciseTax": "102",  # No excise
        "description": str((getattr(product, 'description', '') or product.name)[:1024]),
        "stockPrewarning": str(int(getattr(product, 'min_stock_level', 10))),
        "havePieceUnit": "102",
        "pieceMeasureUnit": "",
        "pieceUnitPrice": "",
        "packageScaledValue": "",
        "pieceScaledValue": "",
        "exciseDutyCode": "",
        "haveOtherUnit": "102",
        "goodsTypeCode": "101"
    }

    # Validate
    print("\nValidating T130 structure:")
    required_fields = ['goodsName', 'goodsCode', 'measureUnit', 'unitPrice',
                       'currency', 'commodityCategoryId', 'haveExciseTax']

    all_valid = True
    for field in required_fields:
        value = goods_data.get(field)
        if value and str(value).strip():
            print(f"  ✅ {field}: {value}")
        else:
            print(f"  ❌ {field}: MISSING or EMPTY")
            all_valid = False

    # Check conditional fields
    if goods_data['havePieceUnit'] == '102':
        if goods_data['pieceMeasureUnit'] == '' and goods_data['pieceUnitPrice'] == '':
            print("  ✅ Piece unit fields correctly empty")
        else:
            print("  ❌ Piece unit fields should be empty when havePieceUnit=102")
            all_valid = False

    # Print JSON
    print("\nT130 JSON structure:")
    print(json.dumps([goods_data], indent=2))

    if all_valid:
        print("\n✅ Product data structure is valid")
        return True
    else:
        print("\n❌ Product data has validation errors")
        return False


def test_invoice_data(company):
    """Test 4: Invoice Data Structure"""
    print("TEST 4: INVOICE DATA STRUCTURE (T109)")
    print("-" * 100)

    from invoices.models import Invoice
    from efris.services import EFRISDataTransformer

    invoice = Invoice.objects.filter(is_fiscalized=False).first()

    if not invoice:
        print("⚠️  No unfiscalized invoices found - skipping test")
        return None

    print(f"\nTesting invoice: {getattr(invoice, 'number', 'N/A')}")

    try:
        transformer = EFRISDataTransformer(company)
        invoice_data = transformer.build_invoice_data(invoice)

        # Check structure
        print("\nValidating invoice structure:")
        required_sections = ['sellerDetails', 'basicInformation', 'buyerDetails',
                             'goodsDetails', 'taxDetails', 'summary']

        all_present = True
        for section in required_sections:
            if section in invoice_data:
                if section == 'goodsDetails':
                    count = len(invoice_data[section])
                    print(f"  ✅ {section}: {count} items")
                else:
                    print(f"  ✅ {section}: Present")
            else:
                print(f"  ❌ {section}: MISSING")
                all_present = False

        # Check amounts
        print("\nValidating amounts:")
        summary = invoice_data.get('summary', {})
        net_amount = float(summary.get('netAmount', 0))
        tax_amount = float(summary.get('taxAmount', 0))
        gross_amount = float(summary.get('grossAmount', 0))

        expected_gross = net_amount + tax_amount
        diff = abs(gross_amount - expected_gross)

        if diff <= 0.01:
            print(f"  ✅ Amount calculation correct:")
            print(f"     Net: {net_amount:,.2f}")
            print(f"     Tax: {tax_amount:,.2f}")
            print(f"     Gross: {gross_amount:,.2f}")
        else:
            print(f"  ❌ Amount mismatch:")
            print(f"     Net + Tax = {expected_gross:,.2f}")
            print(f"     Actual Gross = {gross_amount:,.2f}")
            print(f"     Difference = {diff:,.2f}")
            all_present = False

        # Check goods details
        print("\nGoods details sample:")
        goods = invoice_data.get('goodsDetails', [])
        for idx, item in enumerate(goods[:2], 1):  # Show first 2 items
            print(f"\n  Item {idx}:")
            print(f"    Name: {item.get('item')}")
            print(f"    Code: {item.get('itemCode')}")
            print(f"    Category: {item.get('goodsCategoryId')}")
            print(f"    Qty: {item.get('qty')}, Price: {item.get('unitPrice')}")
            print(f"    Total: {item.get('total')}, Tax: {item.get('tax')}")

        if all_present:
            print("\n✅ Invoice data structure is valid")
            return True
        else:
            print("\n❌ Invoice data has validation errors")
            return False

    except Exception as e:
        print(f"❌ Invoice data test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_live_api(company):
    """Test 5: Live API Communication"""
    print("TEST 5: LIVE API COMMUNICATION")
    print("-" * 100)

    from efris.services import EnhancedEFRISAPIClient

    try:
        with EnhancedEFRISAPIClient(company) as client:

            # Test T101 - Server Time
            print("\nTest T101: Get server time...")
            result = client.get_server_time()

            if result.get('success'):
                print("✅ T101: Server connectivity OK")
            else:
                print(f"❌ T101 failed: {result.get('error')}")
                return False

            # Test Authentication
            print("\nTest Authentication Flow...")
            auth_result = client.ensure_authenticated()

            if auth_result.get('success'):
                print("✅ Authentication: Successful")
            else:
                print(f"❌ Authentication failed: {auth_result.get('error')}")
                return False

            # Test T103 - Login
            print("\nTest T103: Login...")
            if client._is_authenticated:
                print("✅ T103: Login successful")
            else:
                print("❌ T103: Login failed")
                return False

            print("\n✅ Live API communication working")
            return True

    except Exception as e:
        print(f"❌ Live API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def quick_fix_invoice(schema_name, invoice_id):
    """Quick fix and test a specific invoice"""
    print("\n" + "=" * 100)
    print(f"QUICK FIX: Testing Invoice {invoice_id}")
    print("=" * 100)

    with schema_context(schema_name):
        from company.models import Company
        from invoices.models import Invoice
        from efris.services import EnhancedEFRISAPIClient

        company = Company.objects.first()
        invoice = Invoice.objects.get(id=invoice_id)

        print(f"\nInvoice: {invoice.number}")
        print(f"Total: {invoice.total_amount}")

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.upload_invoice(invoice)

                if result.get('success'):
                    print("\n✅ SUCCESS: Invoice fiscalized!")
                    print(f"   FDN: {result.get('data', {}).get('fiscalDocumentNumber', 'N/A')}")
                else:
                    print(f"\n❌ FAILED: {result.get('error')}")
                    print(f"   Error Code: {result.get('error_code')}")

                    # Print detailed error info
                    if result.get('response_data'):
                        print("\nResponse data:")
                        print(json.dumps(result['response_data'], indent=2))

                return result

        except Exception as e:
            print(f"\n❌ Exception: {e}")
            import traceback
            traceback.print_exc()
            return None


# Export functions
__all__ = ['run_all_tests', 'quick_fix_invoice']

