def debug_efris_encryption_complete(company):
    """
    Complete debugging script to test EFRIS encryption process
    """
    print("=" * 80)
    print("EFRIS ENCRYPTION DEBUG SCRIPT")
    print("=" * 80)

    from efris.services import EnhancedEFRISAPIClient

    try:
        client = EnhancedEFRISAPIClient(company)

        # ========== TEST 1: AES Key Retrieval ==========
        print("\n[TEST 1] AES Key Retrieval (T104)")
        print("-" * 80)

        auth_result = client.ensure_authenticated()
        if not auth_result.get("success"):
            print(f"❌ Authentication failed: {auth_result.get('error')}")
            return False

        aes_key = client.security_manager.get_current_aes_key()
        if aes_key:
            print(f"✅ AES Key retrieved: {len(aes_key)} bytes")
            print(f"   Key (hex): {aes_key.hex()}")
        else:
            print("❌ No AES key available")
            return False

        # ========== TEST 2: AES Encryption/Decryption ==========
        print("\n[TEST 2] AES Encryption/Decryption Test")
        print("-" * 80)

        test_data = {"test": "data", "number": 123, "nested": {"key": "value"}}
        test_json = json.dumps(test_data, separators=(',', ':'), ensure_ascii=False)

        print(f"Original JSON: {test_json}")
        print(f"Length: {len(test_json)} chars")

        try:
            # Encrypt
            encrypted = client.security_manager.encrypt_with_aes(test_json, aes_key)
            print(f"✅ Encrypted: {len(encrypted)} chars (base64)")
            print(f"   Sample: {encrypted[:50]}...")

            # Decrypt
            decrypted = client.security_manager.decrypt_with_aes(encrypted, aes_key)
            print(f"✅ Decrypted: {decrypted}")

            if decrypted == test_json:
                print("✅ Encryption/Decryption cycle SUCCESS")
            else:
                print("❌ Decryption mismatch!")
                print(f"   Expected: {test_json}")
                print(f"   Got: {decrypted}")
                return False

        except Exception as e:
            print(f"❌ Encryption test failed: {e}")
            return False

        # ========== TEST 3: RSA Signature ==========
        print("\n[TEST 3] RSA Signature Test")
        print("-" * 80)

        try:
            private_key = client._load_private_key()
            print("✅ Private key loaded")

            # Sign test content
            signature = client.security_manager.sign_content(test_json, private_key)
            print(f"✅ Signature generated: {len(signature)} chars")
            print(f"   Sample: {signature[:50]}...")

        except Exception as e:
            print(f"❌ Signature test failed: {e}")
            return False

        # ========== TEST 4: Full Request Building ==========
        print("\n[TEST 4] Full Request Building")
        print("-" * 80)

        try:
            # Use FIXED function
            request_data = create_signed_encrypted_request_FIXED(
                client.security_manager,
                "T109",
                test_data,
                private_key
            )

            print("✅ Request built successfully")
            print(f"   Content length: {len(request_data['data']['content'])}")
            print(f"   Signature length: {len(request_data['data']['signature'])}")
            print(f"   Interface: {request_data['globalInfo']['interfaceCode']}")

        except Exception as e:
            print(f"❌ Request building failed: {e}")
            return False

        # ========== TEST 5: JSON Serialization Check ==========
        print("\n[TEST 5] JSON Serialization Check")
        print("-" * 80)

        try:
            # Check if request can be serialized
            json_str = json.dumps(request_data, ensure_ascii=False)
            print(f"✅ Request serializable: {len(json_str)} chars")

            # Check for problematic characters
            problematic = [c for c in json_str if ord(c) > 127]
            if problematic:
                print(f"⚠️  Found {len(problematic)} non-ASCII characters")
            else:
                print("✅ No problematic characters")

        except Exception as e:
            print(f"❌ JSON serialization failed: {e}")
            return False

        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED - Encryption process is correct")
        print("=" * 80)
        return True

    except Exception as e:
        print(f"\n❌ Debug script failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# INVOICE-SPECIFIC DEBUG
# ============================================================================

def debug_invoice_data_structure(invoice, company):
    """Debug invoice data structure for T109"""
    print("\n" + "=" * 80)
    print("INVOICE DATA STRUCTURE DEBUG")
    print("=" * 80)

    from efris.services import EFRISDataTransformer

    try:
        transformer = EFRISDataTransformer(company)
        invoice_data = transformer.build_invoice_data(invoice)

        print(f"\n✅ Invoice data built for: {getattr(invoice, 'number', 'unknown')}")

        # Check structure
        required_sections = [
            'sellerDetails', 'basicInformation', 'buyerDetails',
            'goodsDetails', 'taxDetails', 'summary'
        ]

        print("\nStructure Check:")
        for section in required_sections:
            if section in invoice_data:
                print(f"  ✅ {section}")
                if section == 'goodsDetails':
                    print(f"     Items: {len(invoice_data[section])}")
            else:
                print(f"  ❌ {section} MISSING")

        # Check amounts
        print("\nAmount Validation:")
        summary = invoice_data.get('summary', {})
        net_amount = float(summary.get('netAmount', 0))
        tax_amount = float(summary.get('taxAmount', 0))
        gross_amount = float(summary.get('grossAmount', 0))

        expected_gross = net_amount + tax_amount
        if abs(gross_amount - expected_gross) <= 0.01:
            print(f"  ✅ Amounts correct:")
            print(f"     Net: {net_amount}")
            print(f"     Tax: {tax_amount}")
            print(f"     Gross: {gross_amount}")
        else:
            print(f"  ❌ Amount mismatch:")
            print(f"     Net + Tax = {expected_gross}")
            print(f"     Gross = {gross_amount}")
            print(f"     Difference = {abs(gross_amount - expected_gross)}")

        # Check goods details
        print("\nGoods Details Check:")
        goods = invoice_data.get('goodsDetails', [])
        for idx, item in enumerate(goods, 1):
            print(f"\n  Item {idx}:")
            print(f"    Name: {item.get('item')}")
            print(f"    Code: {item.get('itemCode')}")
            print(f"    Category: {item.get('goodsCategoryId')}")
            print(f"    Qty: {item.get('qty')}")
            print(f"    Price: {item.get('unitPrice')}")
            print(f"    Total: {item.get('total')}")
            print(f"    Tax: {item.get('tax')}")

        # Print full JSON
        print("\n" + "=" * 80)
        print("FULL INVOICE JSON:")
        print("=" * 80)
        print(json.dumps(invoice_data, indent=2, ensure_ascii=False))

        return True

    except Exception as e:
        print(f"❌ Invoice debug failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# PRODUCT REGISTRATION DEBUG
# ============================================================================

def debug_product_registration(product, company):
    """Debug product registration data for T130"""
    print("\n" + "=" * 80)
    print("PRODUCT REGISTRATION DEBUG (T130)")
    print("=" * 80)

    try:
        goods_data = build_t130_goods_data_FIXED(product)

        print(f"\n✅ Product data built for: {product.name}")
        print(f"   SKU: {getattr(product, 'sku', 'N/A')}")
        print(f"   ID: {product.id}")

        # Validate required fields
        print("\nRequired Fields Check:")
        required_fields = [
            'goodsName', 'goodsCode', 'measureUnit', 'unitPrice',
            'currency', 'commodityCategoryId', 'haveExciseTax',
            'stockPrewarning', 'havePieceUnit'
        ]

        for field in required_fields:
            value = goods_data.get(field)
            status = "✅" if value and str(value).strip() else "❌"
            print(f"  {status} {field}: {value}")

        # Check conditional fields
        print("\nConditional Fields Check:")
        have_piece_unit = goods_data.get('havePieceUnit')
        if have_piece_unit == '101':
            piece_fields = ['pieceMeasureUnit', 'pieceUnitPrice',
                            'packageScaledValue', 'pieceScaledValue']
            for field in piece_fields:
                value = goods_data.get(field)
                status = "✅" if value else "❌"
                print(f"  {status} {field}: {value}")
        else:
            print(f"  ℹ️  havePieceUnit={have_piece_unit}, piece fields should be empty")

        # Print full JSON
        print("\n" + "=" * 80)
        print("PRODUCT JSON FOR T130:")
        print("=" * 80)
        print(json.dumps([goods_data], indent=2, ensure_ascii=False))

        return True

    except Exception as e:
        print(f"❌ Product debug failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def debug_product_t130_data(product, company):
    """
    Debug what T130 data looks like for a specific product
    """
    print("=" * 70)
    print(f"T130 DEBUG FOR PRODUCT: {product.name} (ID: {product.id})")
    print("=" * 70)

    # Get the data that would be built
    from efris.services import EFRISDataTransformer

    # Simulate building the product data
    commodity_category_id = (
            getattr(product, 'efris_commodity_category_id', None) or
            (getattr(product.category, 'efris_commodity_category_id', None)
             if hasattr(product, 'category') and product.category else None) or
            '10111301'
    )

    goods_code = getattr(product, 'efris_item_code', None)
    if not goods_code:
        goods_code = f"{getattr(product, 'sku', 'PROD')}_{product.id}"

    selling_price = float(getattr(product, 'selling_price', 0) or 0)
    min_stock = int(getattr(product, 'min_stock_level', 0) or 0)
    stock_qty = int(getattr(product, 'quantity_in_stock', 0) or 0)

    # Check for excise
    has_excise = False
    excise_rate = getattr(product, 'excise_duty_rate', None)
    if excise_rate and float(excise_rate) > 0:
        has_excise = True

    print("\n📊 PRODUCT BASIC INFO:")
    print(f"  Name: {product.name}")
    print(f"  SKU: {getattr(product, 'sku', 'N/A')}")
    print(f"  Price: {selling_price}")
    print(f"  Stock: {stock_qty}")
    print(f"  Min Stock: {min_stock}")

    print("\n📋 T130 DATA STRUCTURE:")

    # Build the actual data structure
    goods_data = {
        "operationType": "101",
        "goodsName": str(product.name[:200] if product.name else "Unnamed Product"),
        "goodsCode": str(goods_code),
        "measureUnit": str(getattr(product, 'efris_unit_of_measure_code', None) or "101"),
        "unitPrice": f"{selling_price:.2f}",
        "currency": "101",
        "commodityCategoryId": str(commodity_category_id),
        "haveExciseTax": "101" if has_excise else "102",
        "description": str((getattr(product, 'description', None) or product.name or "")[:1024]),
        "stockPrewarning": str(min_stock),
        "havePieceUnit": "102",
        "pieceMeasureUnit": "",
        "pieceUnitPrice": "",
        "packageScaledValue": "",
        "pieceScaledValue": "",
        "exciseDutyCode": "",
        "haveOtherUnit": "102",
        "goodsTypeCode": "101",
    }

    import json
    print(json.dumps(goods_data, indent=2, ensure_ascii=False))

    print("\n⚠️  VALIDATION CHECKS:")
    errors = []
    warnings = []

    # Check required fields
    if not goods_data['goodsName'] or len(goods_data['goodsName']) < 2:
        errors.append("❌ goodsName is too short (min 2 chars)")
    elif len(goods_data['goodsName']) > 200:
        errors.append("❌ goodsName exceeds 200 chars")
    else:
        print(f"  ✅ goodsName: OK ({len(goods_data['goodsName'])} chars)")

    if not goods_data['goodsCode'] or len(goods_data['goodsCode']) < 1:
        errors.append("❌ goodsCode is empty")
    elif len(goods_data['goodsCode']) > 50:
        errors.append("❌ goodsCode exceeds 50 chars")
    else:
        print(f"  ✅ goodsCode: OK ({goods_data['goodsCode']})")

    if not goods_data['measureUnit'] or goods_data['measureUnit'] not in ['101', '102', '103']:
        warnings.append("⚠️  measureUnit should be valid T115 code (e.g., 101)")
    else:
        print(f"  ✅ measureUnit: OK ({goods_data['measureUnit']})")

    if selling_price <= 0:
        errors.append("❌ unitPrice must be greater than 0")
    else:
        print(f"  ✅ unitPrice: OK ({goods_data['unitPrice']})")

    if goods_data['currency'] != '101':
        warnings.append("⚠️  currency should be 101 (UGX)")
    else:
        print(f"  ✅ currency: OK (101 = UGX)")

    if len(str(commodity_category_id)) < 8:
        errors.append(f"❌ commodityCategoryId too short: {commodity_category_id}")
    else:
        print(f"  ✅ commodityCategoryId: OK ({commodity_category_id})")

    # Check conditional logic
    if goods_data['havePieceUnit'] == '102':
        if goods_data['pieceMeasureUnit'] or goods_data['pieceUnitPrice']:
            errors.append("❌ When havePieceUnit=102, piece fields must be EMPTY")
        else:
            print(f"  ✅ havePieceUnit=102: Piece fields correctly empty")

    if goods_data['haveExciseTax'] == '102':
        if goods_data['exciseDutyCode']:
            errors.append("❌ When haveExciseTax=102, exciseDutyCode must be EMPTY")
        else:
            print(f"  ✅ haveExciseTax=102: exciseDutyCode correctly empty")

    if goods_data['havePieceUnit'] == '102' and goods_data['haveOtherUnit'] == '101':
        errors.append("❌ When havePieceUnit=102, haveOtherUnit MUST be 102")
    else:
        print(f"  ✅ haveOtherUnit: Correctly set to 102")

    print("\n🔍 VALIDATION SUMMARY:")
    if errors:
        print(f"  ❌ ERRORS FOUND ({len(errors)}):")
        for error in errors:
            print(f"     {error}")

    if warnings:
        print(f"  ⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings:
            print(f"     {warning}")

    if not errors and not warnings:
        print("  ✅ ALL CHECKS PASSED!")

    print("\n💡 RECOMMENDATIONS:")
    if errors:
        print("  1. Fix the errors above before attempting T130")
        print("  2. Check your Product model has correct EFRIS fields")
        print("  3. Ensure efris_unit_of_measure_code is set")
    else:
        print("  1. Data structure looks correct")
        print("  2. Try registering this product")
        print("  3. If still fails, check EFRIS response details")

    print("\n" + "=" * 70)

    return {
        'goods_data': goods_data,
        'errors': errors,
        'warnings': warnings,
        'valid': len(errors) == 0
    }


def fix_product_for_efris(product):
    """
    Automatically fix common issues with products before T130
    """
    print(f"\n🔧 FIXING PRODUCT: {product.name}")
    changes = []

    # 1. Set default unit of measure if missing
    if not getattr(product, 'efris_unit_of_measure_code', None):
        product.efris_unit_of_measure_code = '101'  # Default unit
        changes.append("Set efris_unit_of_measure_code = '101'")

    # 2. Generate item code if missing
    if not getattr(product, 'efris_item_code', None):
        item_code = f"{getattr(product, 'sku', 'PROD')}_{product.id}"
        product.efris_item_code = item_code
        changes.append(f"Generated efris_item_code = '{item_code}'")

    # 3. Set default commodity category if missing
    if not getattr(product, 'efris_commodity_category_id', None):
        if hasattr(product, 'category') and product.category:
            if not getattr(product.category, 'efris_commodity_category_id', None):
                product.efris_commodity_category_id = '10111301'
                changes.append("Set default efris_commodity_category_id = '10111301'")
        else:
            product.efris_commodity_category_id = '10111301'
            changes.append("Set default efris_commodity_category_id = '10111301'")

    # 4. Ensure min stock is set
    if not getattr(product, 'min_stock_level', None):
        product.min_stock_level = 10
        changes.append("Set min_stock_level = 10")

    # 5. Ensure price is set
    if not getattr(product, 'selling_price', None) or product.selling_price <= 0:
        print("  ⚠️  WARNING: Product has no valid selling price!")
        changes.append("⚠️  REQUIRES MANUAL FIX: Set selling_price > 0")

    if changes:
        try:
            product.save()
            print("  ✅ Changes saved:")
            for change in changes:
                print(f"     - {change}")
        except Exception as e:
            print(f"  ❌ Failed to save changes: {e}")
    else:
        print("  ℹ️  No fixes needed")

    return changes


def test_single_product_registration(product, company):
    """
    Test registering a single product with full debug output
    """
    print("\n" + "=" * 70)
    print("TESTING SINGLE PRODUCT REGISTRATION")
    print("=" * 70)

    # Step 1: Debug the data
    debug_result = debug_product_t130_data(product, company)

    if not debug_result['valid']:
        print("\n❌ Product has validation errors. Attempting auto-fix...")
        fix_product_for_efris(product)

        # Re-check after fix
        print("\n🔄 RE-CHECKING AFTER FIX...")
        debug_result = debug_product_t130_data(product, company)

        if not debug_result['valid']:
            print("\n❌ Product still has errors. Manual intervention required.")
            return False

    # Step 2: Attempt registration
    print("\n📤 ATTEMPTING T130 REGISTRATION...")
    from efris.services import EnhancedEFRISAPIClient

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.register_product_with_efris(product)

            print("\n📥 T130 RESPONSE:")
            import json
            print(json.dumps(result, indent=2, ensure_ascii=False))

            if result.get('success'):
                print("\n✅ SUCCESS! Product registered with EFRIS")
                return True
            else:
                print(f"\n❌ FAILED: {result.get('error')}")
                print(f"   Error Code: {result.get('error_code')}")

                # Try to decode the error
                if result.get('error_code') == '45':
                    print("\n💡 Error 45 = Partial failure (field validation)")
                    print("   Check the response_data for specific field errors")

                return False

    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


# Quick usage functions
def quick_fix_all_products(company):
    """Fix all products in the company"""
    from inventory.models import Product
    from django_tenants.utils import schema_context

    with schema_context(company.schema_name):
        products = Product.objects.filter(is_active=True, efris_is_uploaded=False)
        print(f"Fixing {products.count()} products...")

        for product in products:
            fix_product_for_efris(product)

        print("✅ All products fixed!")


def debug_failed_product(company, product_id=None, sku=None):
    """Debug a specific failed product"""
    from inventory.models import Product
    from django_tenants.utils import schema_context

    with schema_context(company.schema_name):
        if product_id:
            product = Product.objects.get(id=product_id)
        elif sku:
            product = Product.objects.get(sku=sku)
        else:
            # Get first non-uploaded product
            product = Product.objects.filter(
                is_active=True,
                efris_is_uploaded=False
            ).first()

        if not product:
            print("❌ No product found")
            return

        return test_single_product_registration(product, company)

