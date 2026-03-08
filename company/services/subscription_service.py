import logging
from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing company subscriptions"""

    def upgrade_subscription(self, company, new_plan, billing_cycle, payment_method, upgraded_by):
        """
        Upgrade company to a higher plan

        Args:
            company: Company instance
            new_plan: SubscriptionPlan instance
            billing_cycle: 'MONTHLY', 'QUARTERLY', or 'YEARLY'
            payment_method: Payment method identifier
            upgraded_by: User who initiated the upgrade

        Returns:
            dict: {'success': bool, 'message': str, 'data': dict}
        """
        try:
            # Validate upgrade — block same plan re-upgrade and downgrades
            if company.plan and company.plan.pk == new_plan.pk:
                return {
                    'success': False,
                    'message': 'Company is already on this plan'
                }
            if company.plan and new_plan.price < company.plan.price:
                return {
                    'success': False,
                    'message': 'Cannot upgrade to a lower-priced plan — use downgrade instead'
                }

            # Calculate costs
            cost_breakdown = self._calculate_upgrade_cost(company, new_plan, billing_cycle)

            # Process payment
            payment_result = self._process_payment(
                company=company,
                amount=cost_breakdown['total'],
                payment_method=payment_method,
                description=f"Upgrade to {new_plan.display_name}"
            )

            if not payment_result['success']:
                return payment_result

            # Apply upgrade
            with transaction.atomic():
                # Calculate new subscription period
                duration_days = self._get_duration_days(billing_cycle)

                old_plan = company.plan
                company.plan = new_plan
                company.is_trial = False
                company.subscription_starts_at = timezone.now().date()
                company.subscription_ends_at = company.subscription_starts_at + timedelta(days=duration_days)
                company.grace_period_ends_at = company.subscription_ends_at + timedelta(days=7)
                company.next_billing_date = company.subscription_ends_at
                company.status = 'ACTIVE'
                company.is_active = True
                company.last_payment_date = timezone.now().date()
                company.payment_method = payment_method

                # Add note
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                note = (
                    f"\n[{timestamp}] Upgraded from {old_plan.display_name if old_plan else 'None'} "
                    f"to {new_plan.display_name} by {upgraded_by.get_full_name() or upgraded_by.username}"
                )
                company.notes = (company.notes or '') + note

                company.save()

                # Reactivate users if previously suspended
                company.reactivate_all_users()

                # Create invoice/receipt
                invoice = self._create_invoice(
                    company=company,
                    plan=new_plan,
                    amount=cost_breakdown['total'],
                    billing_cycle=billing_cycle,
                    transaction_type='UPGRADE',
                    payment_method=payment_method,
                    breakdown=cost_breakdown
                )

                logger.info(
                    f"Company {company.company_id} upgraded to {new_plan.name} "
                    f"by {upgraded_by.username}"
                )

                return {
                    'success': True,
                    'message': f'Successfully upgraded to {new_plan.display_name}',
                    'data': {
                        'company_id': company.company_id,
                        'plan': new_plan.name,
                        'subscription_ends_at': company.subscription_ends_at.isoformat(),
                        'invoice_id': invoice.id if invoice else None,
                        'cost_breakdown': cost_breakdown,
                    }
                }

        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Upgrade failed: {str(e)}'
            }

    def downgrade_subscription(self, company, new_plan, downgraded_by):
        """
        Downgrade company to a lower plan (effective at end of current period)

        Args:
            company: Company instance
            new_plan: SubscriptionPlan instance
            downgraded_by: User who initiated the downgrade

        Returns:
            dict: {'success': bool, 'message': str, 'data': dict}
        """
        try:
            # Validate downgrade
            if company.plan and new_plan.price >= company.plan.price:
                return {
                    'success': False,
                    'message': 'Cannot downgrade to a plan with equal or higher price'
                }

            # Check if company meets new plan limits
            validation = self._validate_plan_limits(company, new_plan)
            if not validation['valid']:
                return {
                    'success': False,
                    'message': 'Cannot downgrade due to usage limits',
                    'issues': validation['issues']
                }

            # Schedule downgrade for end of current period
            with transaction.atomic():
                old_plan = company.plan

                # Store scheduled downgrade info
                scheduled_changes = company.notes or ''
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                note = (
                    f"\n[{timestamp}] Downgrade scheduled from {old_plan.display_name} "
                    f"to {new_plan.display_name} by {downgraded_by.get_full_name() or downgraded_by.username}. "
                    f"Effective: {company.subscription_ends_at}"
                )
                company.notes = scheduled_changes + note
                company.save(update_fields=['notes'])

                # TODO: Create scheduled task to apply downgrade at subscription_ends_at
                # For now, we'll need a management command or celery task

                logger.info(
                    f"Company {company.company_id} scheduled downgrade to {new_plan.name} "
                    f"by {downgraded_by.username}, effective {company.subscription_ends_at}"
                )

                return {
                    'success': True,
                    'message': f'Downgrade to {new_plan.display_name} scheduled',
                    'data': {
                        'company_id': company.company_id,
                        'current_plan': old_plan.name,
                        'new_plan': new_plan.name,
                        'effective_date': company.subscription_ends_at.isoformat(),
                    }
                }

        except Exception as e:
            logger.error(f"Error scheduling downgrade: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Downgrade failed: {str(e)}'
            }

    def renew_subscription(self, company, billing_cycle, payment_method, renewed_by):
        """
        Renew current subscription

        Args:
            company: Company instance
            billing_cycle: 'MONTHLY', 'QUARTERLY', or 'YEARLY'
            payment_method: Payment method identifier
            renewed_by: User who initiated the renewal

        Returns:
            dict: {'success': bool, 'message': str, 'data': dict}
        """
        try:
            if not company.plan:
                return {
                    'success': False,
                    'message': 'No active plan to renew'
                }

            plan = company.plan
            amount = plan.price

            # Process payment
            payment_result = self._process_payment(
                company=company,
                amount=amount,
                payment_method=payment_method,
                description=f"Renewal of {plan.display_name}"
            )

            if not payment_result['success']:
                return payment_result

            # Apply renewal
            with transaction.atomic():
                duration_days = self._get_duration_days(billing_cycle)

                # Extend from current end date or today (whichever is later)
                start_date = max(
                    timezone.now().date(),
                    company.subscription_ends_at or timezone.now().date()
                )

                company.subscription_ends_at = start_date + timedelta(days=duration_days)
                company.grace_period_ends_at = company.subscription_ends_at + timedelta(days=7)
                company.next_billing_date = company.subscription_ends_at
                company.last_payment_date = timezone.now().date()
                company.payment_method = payment_method
                company.status = 'ACTIVE'
                company.is_active = True

                # Add note
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                note = (
                    f"\n[{timestamp}] Subscription renewed for {billing_cycle} "
                    f"by {renewed_by.get_full_name() or renewed_by.username}"
                )
                company.notes = (company.notes or '') + note

                company.save()

                # Reactivate if was suspended
                company.reactivate_all_users()

                # Create invoice
                invoice = self._create_invoice(
                    company=company,
                    plan=plan,
                    amount=amount,
                    billing_cycle=billing_cycle,
                    transaction_type='RENEWAL',
                    payment_method=payment_method
                )

                logger.info(
                    f"Company {company.company_id} renewed subscription "
                    f"by {renewed_by.username}"
                )

                return {
                    'success': True,
                    'message': 'Subscription renewed successfully',
                    'data': {
                        'company_id': company.company_id,
                        'plan': plan.name,
                        'subscription_ends_at': company.subscription_ends_at.isoformat(),
                        'invoice_id': invoice.id if invoice else None,
                    }
                }

        except Exception as e:
            logger.error(f"Error renewing subscription: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Renewal failed: {str(e)}'
            }

    def cancel_subscription(self, company, reason, immediate, cancelled_by):
        """
        Cancel subscription

        Args:
            company: Company instance
            reason: Cancellation reason
            immediate: If True, cancel immediately; if False, at period end
            cancelled_by: User who cancelled

        Returns:
            dict: {'success': bool, 'message': str, 'data': dict}
        """
        try:
            with transaction.atomic():
                timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")

                if immediate:
                    # Immediate cancellation
                    company.status = 'SUSPENDED'
                    company.is_active = False
                    # NOTE: deactivate_all_users() touches the tenant schema and is
                    # called AFTER the atomic block commits to avoid cross-schema
                    # operations inside a public-schema transaction.

                    note = (
                        f"\n[{timestamp}] Subscription cancelled immediately "
                        f"by {cancelled_by.get_full_name() or cancelled_by.username}. "
                        f"Reason: {reason}"
                    )
                else:
                    # Cancel at period end
                    note = (
                        f"\n[{timestamp}] Subscription cancellation scheduled for "
                        f"{company.subscription_ends_at} "
                        f"by {cancelled_by.get_full_name() or cancelled_by.username}. "
                        f"Reason: {reason}"
                    )

                company.notes = (company.notes or '') + note
                company.save()

            # Deactivate tenant users outside the atomic block (cross-schema safety)
            if immediate:
                try:
                    company.deactivate_all_users()
                except Exception as e:
                    logger.error(
                        f"Failed to deactivate users for company {company.company_id} "
                        f"after cancellation: {e}", exc_info=True
                    )

            logger.info(
                f"Company {company.company_id} subscription cancelled "
                f"({'immediately' if immediate else 'at period end'}) "
                f"by {cancelled_by.username}"
            )

            return {
                'success': True,
                'message': 'Subscription cancelled' + (' immediately' if immediate else ''),
                'data': {
                    'company_id': company.company_id,
                        'immediate': immediate,
                        'effective_date': timezone.now().date().isoformat() if immediate else company.subscription_ends_at.isoformat(),
                    }
                }

        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}", exc_info=True)
            return {
                'success': False,
                'message': f'Cancellation failed: {str(e)}'
            }

    def _calculate_upgrade_cost(self, company, new_plan, billing_cycle):
        """Calculate upgrade cost with proration"""
        cost_breakdown = {
            'plan_cost': new_plan.price,
            'setup_fee': new_plan.setup_fee,
            'proration_credit': Decimal('0.00'),
            'subtotal': Decimal('0.00'),
            'total': Decimal('0.00'),
        }

        # Calculate proration credit using Decimal arithmetic throughout
        if company.subscription_ends_at and not company.is_trial and company.plan:
            days_remaining = (company.subscription_ends_at - timezone.now().date()).days
            if days_remaining > 0:
                current_daily_rate = company.plan.price / Decimal('30')
                cost_breakdown['proration_credit'] = current_daily_rate * Decimal(days_remaining)

        cost_breakdown['subtotal'] = (
                cost_breakdown['plan_cost'] +
                cost_breakdown['setup_fee'] -
                cost_breakdown['proration_credit']
        )
        cost_breakdown['total'] = max(cost_breakdown['subtotal'], Decimal('0.00'))

        return cost_breakdown

    def _validate_plan_limits(self, company, new_plan):
        """Validate if company can fit within new plan limits"""
        from accounts.models import CustomUser

        issues = []

        # Check users — only count active, non-hidden users since deactivated
        # users don't consume plan capacity
        current_users = CustomUser.objects.filter(
            company=company, is_hidden=False, is_active=True
        ).count()
        if current_users > new_plan.max_users:
            issues.append(f'Too many users: {current_users} > {new_plan.max_users}')

        # Check branches
        if company.branches_count > new_plan.max_branches:
            issues.append(f'Too many branches: {company.branches_count} > {new_plan.max_branches}')

        # Check storage
        storage_gb = company.storage_used_mb / 1024
        if storage_gb > new_plan.max_storage_gb:
            issues.append(f'Storage exceeds limit: {storage_gb:.2f}GB > {new_plan.max_storage_gb}GB')

        return {
            'valid': len(issues) == 0,
            'issues': issues
        }

    def _get_duration_days(self, billing_cycle):
        """Get duration in days for billing cycle"""
        durations = {
            'MONTHLY': 30,
            'QUARTERLY': 90,
            'YEARLY': 365,
        }
        return durations.get(billing_cycle, 30)

    def _process_payment(self, company, amount, payment_method, description):
        """
        Process payment through payment gateway

        This is a placeholder - integrate with actual payment processor
        (Stripe, PayPal, Flutterwave, etc.)
        """
        # TODO: Integrate with actual payment gateway
        logger.info(
            f"Processing payment: {amount} {company.preferred_currency} "
            f"for {company.company_id} via {payment_method}"
        )

        # For now, simulate successful payment
        return {
            'success': True,
            'transaction_id': f'TXN_{timezone.now().timestamp()}',
            'message': 'Payment processed successfully'
        }

    def _create_invoice(self, company, plan, amount, billing_cycle,
                        transaction_type, payment_method, breakdown=None):
        """
        Create invoice/receipt for the transaction

        TODO: Create proper Invoice model and implementation
        """
        logger.info(
            f"Creating invoice for {company.company_id}: "
            f"{transaction_type} - {amount} {company.preferred_currency}"
        )

        # Placeholder - implement actual invoice creation
        return None