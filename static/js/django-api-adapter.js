/**
 * Django API Data Adapter
 * Transforms Django model data to IndexedDB format and vice versa
 */

class DjangoAPIAdapter {
  constructor() {
    this.fieldMappings = this.initializeFieldMappings();
  }

  /**
   * Initialize field mappings between Django and IndexedDB
   */
  initializeFieldMappings() {
    return {
      // Product model mappings
      product: {
        django_to_db: {
          'id': 'id',
          'category_id': 'category_id',
          'supplier_id': 'supplier_id',
          'name': 'name',
          'sku': 'sku',
          'barcode': 'barcode',
          'description': 'description',
          'selling_price': 'selling_price',
          'cost_price': 'cost_price',
          'discount_percentage': 'discount_percentage',
          'tax_rate': 'tax_rate',
          'excise_duty_rate': 'excise_duty_rate',
          'unit_of_measure': 'unit_of_measure',
          'min_stock_level': 'min_stock_level',
          'is_active': 'is_active',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
          'efris_is_uploaded': 'efris_is_uploaded',
          'efris_goods_code_field': 'efris_goods_code_field',
        }
      },

      // Service model mappings
      service: {
        django_to_db: {
          'id': 'id',
          'category_id': 'category_id',
          'name': 'name',
          'code': 'code',
          'description': 'description',
          'unit_price': 'unit_price',
          'tax_rate': 'tax_rate',
          'excise_duty_rate': 'excise_duty_rate',
          'unit_of_measure': 'unit_of_measure',
          'is_active': 'is_active',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
          'efris_is_uploaded': 'efris_is_uploaded',
        }
      },

      // Category model mappings
      category: {
        django_to_db: {
          'id': 'id',
          'name': 'name',
          'code': 'code',
          'description': 'description',
          'category_type': 'category_type',
          'efris_commodity_category_code': 'efris_commodity_category_code',
          'is_active': 'is_active',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
        }
      },

      // Stock model mappings
      stock: {
        django_to_db: {
          'id': 'id',
          'product_id': 'product_id',
          'store_id': 'store_id',
          'quantity': 'quantity',
          'low_stock_threshold': 'low_stock_threshold',
          'reorder_quantity': 'reorder_quantity',
          'last_updated': 'last_updated',
          'last_physical_count': 'last_physical_count',
        }
      },

      // StockMovement model mappings
      stock_movements: {
        django_to_db: {
          'id': 'id',
          'product_id': 'product_id',
          'store_id': 'store_id',
          'movement_type': 'movement_type',
          'quantity': 'quantity',
          'reference': 'reference',
          'notes': 'notes',
          'unit_price': 'unit_price',
          'total_value': 'total_value',
          'created_by_id': 'created_by_id',
          'created_at': 'created_at',
          'synced_to_efris': 'synced_to_efris',
        }
      },

      // Sale model mappings
      sales: {
        django_to_db: {
          'id': 'id',
          'transaction_id': 'transaction_id',
          'document_number': 'document_number',
          'document_type': 'document_type',
          'store_id': 'store_id',
          'created_by_id': 'created_by_id',
          'customer_id': 'customer_id',
          'transaction_type': 'transaction_type',
          'payment_method': 'payment_method',
          'currency': 'currency',
          'due_date': 'due_date',
          'subtotal': 'subtotal',
          'tax_amount': 'tax_amount',
          'discount_amount': 'discount_amount',
          'total_amount': 'total_amount',
          'efris_invoice_number': 'efris_invoice_number',
          'verification_code': 'verification_code',
          'qr_code': 'qr_code',
          'is_fiscalized': 'is_fiscalized',
          'fiscalization_time': 'fiscalization_time',
          'status': 'status',
          'payment_status': 'payment_status',
          'is_refunded': 'is_refunded',
          'is_voided': 'is_voided',
          'notes': 'notes',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
        }
      },

      // Customer model mappings
      customers: {
        django_to_db: {
          'id': 'id',
          'customer_id': 'customer_id',
          'customer_type': 'customer_type',
          'name': 'name',
          'store_id': 'store_id',
          'email': 'email',
          'phone': 'phone',
          'tin': 'tin',
          'nin': 'nin',
          'brn': 'brn',
          'physical_address': 'physical_address',
          'postal_address': 'postal_address',
          'is_active': 'is_active',
          'credit_limit': 'credit_limit',
          'credit_balance': 'credit_balance',
          'allow_credit': 'allow_credit',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
        }
      },

      // Store model mappings
      stores: {
        django_to_db: {
          'id': 'id',
          'company_id': 'company_id',
          'name': 'name',
          'code': 'code',
          'store_type': 'store_type',
          'physical_address': 'physical_address',
          'phone': 'phone',
          'email': 'email',
          'efris_device_number': 'efris_device_number',
          'efris_enabled': 'efris_enabled',
          'is_active': 'is_active',
          'created_at': 'created_at',
          'updated_at': 'updated_at',
        }
      }
    };
  }

  /**
   * Transform Django API response to IndexedDB format
   */
  transformFromDjango(entityType, djangoData) {
    const mapping = this.fieldMappings[entityType];
    if (!mapping) {
      console.warn(`No mapping found for entity type: ${entityType}`);
      return djangoData;
    }

    const transformed = {};
    for (const [djangoField, dbField] of Object.entries(mapping.django_to_db)) {
      if (djangoData.hasOwnProperty(djangoField)) {
        transformed[dbField] = djangoData[djangoField];
      }
    }

    // Add sync status
    transformed.sync_status = 'synced';
    transformed.last_synced = new Date().toISOString();

    return transformed;
  }

  /**
   * Transform IndexedDB data to Django API format
   */
  transformToDjango(entityType, dbData) {
    const mapping = this.fieldMappings[entityType];
    if (!mapping) {
      console.warn(`No mapping found for entity type: ${entityType}`);
      return dbData;
    }

    const transformed = {};
    const reverseMapping = this.reverseMapping(mapping.django_to_db);

    for (const [dbField, djangoField] of Object.entries(reverseMapping)) {
      if (dbData.hasOwnProperty(dbField) &&
          !['sync_status', 'last_synced', 'version', 'updated_by'].includes(dbField)) {
        transformed[djangoField] = dbData[dbField];
      }
    }

    return transformed;
  }

  /**
   * Reverse a field mapping
   */
  reverseMapping(mapping) {
    const reversed = {};
    for (const [key, value] of Object.entries(mapping)) {
      reversed[value] = key;
    }
    return reversed;
  }

  /**
   * Transform bulk Django data (for initial sync)
   */
  transformBulkFromDjango(entityType, djangoDataArray) {
    return djangoDataArray.map(item => this.transformFromDjango(entityType, item));
  }

  /**
   * Prepare sale data for Django API (special handling)
   */
  prepareSaleForDjango(saleData, saleItems) {
    // Transform main sale data
    const transformedSale = this.transformToDjango('sales', saleData);

    // Transform sale items
    const transformedItems = saleItems.map(item => ({
      product_id: item.product_id || null,
      service_id: item.service_id || null,
      item_type: item.item_type || 'PRODUCT',
      quantity: item.quantity,
      unit_price: item.unit_price,
      total_price: item.total_price,
      tax_rate: item.tax_rate,
      tax_amount: item.tax_amount,
      discount: item.discount || 0,
      discount_amount: item.discount_amount || 0,
      description: item.description || '',
    }));

    return {
      ...transformedSale,
      items: transformedItems
    };
  }

  /**
   * Parse Django DRF response format
   */
  parseDRFResponse(response) {
    // Handle DRF paginated response
    if (response.results) {
      return {
        results: response.results,
        count: response.count,
        next: response.next,
        previous: response.previous
      };
    }

    // Handle single object response
    return response;
  }

  /**
   * Handle Django validation errors
   */
  handleDjangoError(errorResponse) {
    if (errorResponse.detail) {
      return errorResponse.detail;
    }

    if (typeof errorResponse === 'object') {
      const errors = [];
      for (const [field, messages] of Object.entries(errorResponse)) {
        if (Array.isArray(messages)) {
          errors.push(`${field}: ${messages.join(', ')}`);
        } else {
          errors.push(`${field}: ${messages}`);
        }
      }
      return errors.join('; ');
    }

    return 'An error occurred';
  }

  /**
   * Generate client-side ID that matches Django format
   */
  generateClientId(prefix = 'offline') {
    const timestamp = Date.now();
    const random = Math.random().toString(36).substr(2, 9);
    return `${prefix}_${timestamp}_${random}`;
  }

  /**
   * Check if ID is client-generated
   */
  isClientId(id) {
    return typeof id === 'string' && id.startsWith('offline_');
  }

  /**
   * Prepare data for offline creation
   */
  prepareForOfflineCreation(entityType, data, userId) {
    const prepared = {
      ...data,
      id: this.generateClientId(entityType),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      created_by_id: userId,
      sync_status: 'pending',
      version: 1,
    };

    return prepared;
  }

  /**
   * Map Django choice values
   */
  getDjangoChoiceValue(field, value) {
    const choiceMappings = {
      document_type: {
        'RECEIPT': 'RECEIPT',
        'INVOICE': 'INVOICE',
        'PROFORMA': 'PROFORMA',
        'ESTIMATE': 'ESTIMATE',
      },
      payment_method: {
        'CASH': 'CASH',
        'CARD': 'CARD',
        'MOBILE_MONEY': 'MOBILE_MONEY',
        'BANK_TRANSFER': 'BANK_TRANSFER',
        'VOUCHER': 'VOUCHER',
        'CREDIT': 'CREDIT',
      },
      tax_rate: {
        'A': 'A', // Standard 18%
        'B': 'B', // Zero rate
        'C': 'C', // Exempt
        'D': 'D', // Deemed
        'E': 'E', // Excise duty
      },
      status: {
        'DRAFT': 'DRAFT',
        'PENDING_PAYMENT': 'PENDING_PAYMENT',
        'PARTIALLY_PAID': 'PARTIALLY_PAID',
        'PAID': 'PAID',
        'COMPLETED': 'COMPLETED',
        'OVERDUE': 'OVERDUE',
        'VOIDED': 'VOIDED',
        'REFUNDED': 'REFUNDED',
        'CANCELLED': 'CANCELLED',
      }
    };

    if (choiceMappings[field] && choiceMappings[field][value]) {
      return choiceMappings[field][value];
    }

    return value;
  }

  /**
   * Validate data against Django model constraints
   */
  validateForDjango(entityType, data) {
    const errors = [];

    // Entity-specific validation
    switch(entityType) {
      case 'sales':
        if (!data.store_id) errors.push('Store is required');
        if (!data.document_type) errors.push('Document type is required');
        if (!data.total_amount || data.total_amount <= 0) errors.push('Total amount must be positive');
        break;

      case 'product':
        if (!data.name) errors.push('Product name is required');
        if (!data.sku) errors.push('SKU is required');
        if (!data.selling_price || data.selling_price < 0) errors.push('Valid selling price required');
        break;

      case 'customers':
        if (!data.name) errors.push('Customer name is required');
        if (!data.phone) errors.push('Phone number is required');
        if (data.customer_type === 'BUSINESS' && !data.tin) {
          errors.push('TIN is required for business customers');
        }
        break;
    }

    return {
      isValid: errors.length === 0,
      errors: errors
    };
  }
}

// Export singleton instance
const djangoAPIAdapter = new DjangoAPIAdapter();
export default djangoAPIAdapter;