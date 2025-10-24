import csv
import io
import pandas as pd
from django.http import HttpResponse
from datetime import datetime
from rest_framework.renderers import JSONRenderer
from customers.serializers import CustomerTaxInfoSerializer, CustomerSerializer


class CustomerExporter:
    def __init__(self, queryset, export_format, include_tax_info=True):
        self.queryset = queryset
        self.format = export_format.upper()  # Normalize format for safety
        self.include_tax_info = include_tax_info
    
    def export(self):
        if self.format == 'CSV':
            return self.export_csv()
        elif self.format == 'XLSX':
            return self.export_excel()
        else:  # Default JSON
            return self.export_json()
    
    def export_csv(self):
        response = HttpResponse(content_type='text/csv')
        filename = f"customers_{datetime.now().strftime('%Y%m%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(self.get_headers())
        
        for customer in self.queryset:
            writer.writerow(self.get_row_data(customer))
            
        return response
    
    def export_excel(self):
        output = io.BytesIO()
        
        data = [self.get_headers()]
        data.extend([self.get_row_data(customer) for customer in self.queryset])
        
        df = pd.DataFrame(data[1:], columns=data[0])
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        
        output.seek(0)
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        filename = f"customers_{datetime.now().strftime('%Y%m%d')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    def export_json(self):
        serializer_class = CustomerTaxInfoSerializer if self.include_tax_info else CustomerSerializer
        data = serializer_class(self.queryset, many=True).data
        return HttpResponse(
            JSONRenderer().render(data),
            content_type='application/json'
        )

    def get_headers(self):
        base_headers = [
            'customer_id', 'name', 'customer_type', 
            'email', 'phone', 'physical_address',
            'postal_address', 'district', 'country'
        ]
        
        if self.include_tax_info:
            base_headers.extend(['tin', 'nin', 'brn', 'is_vat_registered'])
            
        return base_headers
    
    def get_row_data(self, customer):
        base_data = [
            customer.customer_id,
            customer.name,
            customer.customer_type,
            customer.email,
            customer.phone,
            customer.physical_address,
            customer.postal_address,
            customer.district,
            customer.country
        ]
        
        if self.include_tax_info:
            base_data.extend([
                customer.tin,
                customer.nin,
                customer.brn,
                customer.is_vat_registered
            ])
            
        return base_data
