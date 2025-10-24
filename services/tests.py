from django.test import TestCase
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import (
    Service, ServiceType, ServiceCategory, ServiceAppointment,
    ServicePackage, ServicePackageItem
)

User = get_user_model()


class ServiceModelTest(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Beauty")
        self.service_type = ServiceType.objects.create(
            name="Haircut",
            pricing_type=ServiceType.FIXED
        )
        self.service = Service.objects.create(
            name="Men's Haircut",
            code="HC001",
            category=self.category,
            service_type=self.service_type,
            base_price=Decimal('25.00'),
            tax_rate=Decimal('10.00')
        )

    def test_service_creation(self):
        self.assertEqual(self.service.name, "Men's Haircut")
        self.assertEqual(self.service.base_price, Decimal('25.00'))

    def test_price_calculation(self):
        price = self.service.calculate_price()
        self.assertEqual(price, Decimal('25.00'))

    def test_tax_calculation(self):
        tax = self.service.calculate_tax(Decimal('25.00'))
        self.assertEqual(tax, Decimal('2.50'))


class ServiceAppointmentTest(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Beauty")
        self.service_type = ServiceType.objects.create(
            name="Haircut",
            pricing_type=ServiceType.FIXED
        )
        self.service = Service.objects.create(
            name="Men's Haircut",
            code="HC001",
            category=self.category,
            service_type=self.service_type,
            base_price=Decimal('25.00'),
            default_duration=30
        )
        self.appointment = ServiceAppointment.objects.create(
            service=self.service,
            customer_name="John Doe",
            customer_email="john@example.com",
            scheduled_date="2025-10-22",
            scheduled_time="10:00:00",
            duration_minutes=30,
            price=Decimal('25.00'),
            total_amount=Decimal('27.50')
        )

    def test_appointment_number_generation(self):
        self.assertTrue(self.appointment.appointment_number.startswith('APT'))

    def test_appointment_status_change(self):
        self.appointment.status = ServiceAppointment.CONFIRMED
        self.appointment.save()
        self.assertEqual(self.appointment.status, ServiceAppointment.CONFIRMED)


class ServicePackageTest(TestCase):
    def setUp(self):
        self.category = ServiceCategory.objects.create(name="Beauty")
        self.service_type = ServiceType.objects.create(
            name="Haircut",
            pricing_type=ServiceType.FIXED
        )
        self.service1 = Service.objects.create(
            name="Haircut",
            code="HC001",
            category=self.category,
            service_type=self.service_type,
            base_price=Decimal('25.00')
        )
        self.service2 = Service.objects.create(
            name="Beard Trim",
            code="BT001",
            category=self.category,
            service_type=self.service_type,
            base_price=Decimal('15.00')
        )
        self.package = ServicePackage.objects.create(
            name="Grooming Package",
            code="PKG001",
            price=Decimal('35.00')
        )
        ServicePackageItem.objects.create(
            package=self.package,
            service=self.service1,
            quantity=1
        )
        ServicePackageItem.objects.create(
            package=self.package,
            service=self.service2,
            quantity=1
        )

    def test_package_total_value(self):
        total = self.package.calculate_total_value()
        self.assertEqual(total, Decimal('40.00'))

    def test_package_savings(self):
        savings = self.package.calculate_savings()
        self.assertEqual(savings, Decimal('5.00'))
