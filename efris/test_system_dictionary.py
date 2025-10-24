def test_system_dictionary_update(company):
    print("=" * 70)
    print("TESTING T115 - SYSTEM DICTIONARY UPDATE")
    print("=" * 70)

    from efris.services import SystemDictionaryManager
    from django.core.cache import cache

    results = {
        'success': False,
        'cached_data': None,
        'db_data': None,
        'errors': []
    }

    try:
        manager = SystemDictionaryManager(company)

        cache_key = f"efris_system_dict_{company.pk}"
        cache.delete(cache_key)
        print("✓ Cleared cached dictionary")

        print("\n1. Fetching system dictionary from EFRIS...")
        result = manager.update_system_dictionary(force_update=True)

        if not result.get('success'):
            print(f"❌ Update failed: {result.get('error')}")
            results['errors'].append(result.get('error'))
            return results

        print(f"✓ Dictionary updated successfully")
        print(f"  Cached: {result.get('cached', False)}")

        print("\n2. Verifying cached data...")
        cached_dict = cache.get(cache_key)

        if not cached_dict:
            print("❌ No cached dictionary found")
            results['errors'].append("Cache verification failed")
        else:
            print(f"✓ Dictionary cached successfully")
            print(f"  Dictionary keys: {list(cached_dict.keys())[:10]}...")
            results['cached_data'] = cached_dict

        print("\n3. Verifying database storage...")
        from efris.models import EFRISSystemDictionary

        try:
            dict_obj = EFRISSystemDictionary.objects.get(company=company)
            print(f"✓ Dictionary stored in database")
            print(f"  Last updated: {dict_obj.last_updated}")
            print(f"  Data keys: {list(dict_obj.data.keys())[:10]}...")
            results['db_data'] = dict_obj.data
        except EFRISSystemDictionary.DoesNotExist:
            print("❌ No dictionary found in database")
            results['errors'].append("Database verification failed")

        # Test 4: Verify specific dictionary categories
        print("\n4. Testing dictionary value retrieval...")

        test_categories = [
            ('payWay', None, 'Payment modes'),
            ('currencyType', None, 'Currency types'),
            ('rateUnit', None, 'Unit of measure'),
            ('taxRate', None, 'Tax rates')
        ]

        for category, code, description in test_categories:
            value = manager.get_dictionary_value(category, code)

            if value:
                print(f"✓ {description} ({category}): Found")
                if isinstance(value, list):
                    print(f"    Total items: {len(value)}")
                    if value:
                        print(f"    Sample: {value[0]}")
            else:
                print(f"⚠ {description} ({category}): Not found")

        # Test 5: Test cache expiry behavior
        print("\n5. Testing cache behavior...")

        # This should use cached version
        result2 = manager.update_system_dictionary(force_update=False)

        if result2.get('cached'):
            print("✓ Using cached dictionary (as expected)")
        else:
            print("⚠ Fresh fetch when cache should be used")

        # Test 6: Validate dictionary structure
        print("\n6. Validating dictionary structure...")

        if cached_dict:
            validation_errors = _validate_dictionary_structure(cached_dict)

            if validation_errors:
                print(f"⚠ Structure validation warnings:")
                for error in validation_errors[:5]:  # Show first 5
                    print(f"    - {error}")
            else:
                print("✓ Dictionary structure is valid")

        results['success'] = len(results['errors']) == 0

        # Summary
        print("\n" + "=" * 70)
        if results['success']:
            print("✅ T115 TEST PASSED - System dictionary working correctly")
        else:
            print("❌ T115 TEST FAILED")
            print(f"Errors: {results['errors']}")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ TEST EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        results['errors'].append(str(e))

    return results



def _validate_dictionary_structure(dictionary: dict) -> list:
    """Validate expected dictionary structure"""
    errors = []

    # Expected categories based on EFRIS documentation
    expected_categories = [
        'payWay',  # Payment modes
        'currencyType',  # Currency types
        'rateUnit',  # Units of measure
        'taxRate',  # Tax rates
        'goodsType',  # Goods types
        'invoiceType',  # Invoice types
    ]

    for category in expected_categories:
        if category not in dictionary:
            errors.append(f"Missing expected category: {category}")
        else:
            # Validate category has data
            data = dictionary[category]
            if not data:
                errors.append(f"Empty category: {category}")
            elif not isinstance(data, (list, dict)):
                errors.append(f"Invalid data type for {category}: {type(data)}")

    return errors


def test_dictionary_specific_lookups(company):
    """Test specific dictionary value lookups"""
    print("\n" + "=" * 70)
    print("TESTING DICTIONARY VALUE LOOKUPS")
    print("=" * 70)

    from efris.services import SystemDictionaryManager

    manager = SystemDictionaryManager(company)

    # Test payment modes
    print("\n1. Payment Modes (payWay):")
    payment_modes = manager.get_dictionary_value('payWay')

    if payment_modes:
        print(f"   Total payment modes: {len(payment_modes) if isinstance(payment_modes, list) else 'N/A'}")

        # Look for specific codes
        for code in ['102', '105', '106', '107']:  # Cash, Mobile Money, Card, Bank
            mode = manager.get_dictionary_value('payWay', code)
            if mode:
                name = mode.get('name', 'N/A') if isinstance(mode, dict) else mode
                print(f"   ✓ Code {code}: {name}")

    # Test currency types
    print("\n2. Currency Types (currencyType):")
    currencies = manager.get_dictionary_value('currencyType')

    if currencies:
        print(f"   Total currencies: {len(currencies) if isinstance(currencies, list) else 'N/A'}")

        # Look for UGX
        ugx = manager.get_dictionary_value('currencyType', '101')
        if ugx:
            print(f"   ✓ UGX found: {ugx}")

    # Test units of measure
    print("\n3. Units of Measure (rateUnit):")
    units = manager.get_dictionary_value('rateUnit')

    if units:
        print(f"   Total units: {len(units) if isinstance(units, list) else 'N/A'}")
        if isinstance(units, list) and units:
            print(f"   Sample units: {[u.get('name', 'N/A') for u in units[:5]]}")


# Usage example:
if __name__ == "__main__":
    from company.models import Company

    # Get your company
    company = Company.objects.get(company_id='PF-N278119')

    # Run comprehensive test
    results = test_system_dictionary_update(company)

    # Run specific lookup tests
    test_dictionary_specific_lookups(company)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Overall success: {results['success']}")
    print(f"Cached data available: {results['cached_data'] is not None}")
    print(f"Database data available: {results['db_data'] is not None}")
    if results['errors']:
        print(f"\nErrors encountered:")
        for error in results['errors']:
            print(f"  - {error}")