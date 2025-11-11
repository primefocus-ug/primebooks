from django.core.files.base import ContentFile
from django.utils import timezone
from datetime import timedelta
import zipfile
import io
import json
import pyzipper  # For password-protected zips
from .models import (
    Message, Conversation, ConversationParticipant,
    LegalAccessRequest, LegalAccessLog
)
from .services import EncryptionService
import secrets
import string


class LegalAccessService:
    """
    Handle legal/law enforcement access to encrypted messages

    IMPORTANT: Use with extreme caution and proper authorization
    """

    @staticmethod
    def create_access_request(
            request_number,
            request_type,
            authority_name,
            authority_contact,
            target_user,
            legal_document,
            request_description,
            target_conversation=None,
            date_range_start=None,
            date_range_end=None,
            retention_days=90
    ):
        """
        Create a legal access request

        Must be done by authorized personnel only
        """
        retention_until = timezone.now().date() + timedelta(days=retention_days)

        request = LegalAccessRequest.objects.create(
            request_number=request_number,
            request_type=request_type,
            authority_name=authority_name,
            authority_contact=authority_contact,
            target_user=target_user,
            target_conversation=target_conversation,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            legal_document=legal_document,
            request_description=request_description,
            retention_until=retention_until,
        )

        return request

    @staticmethod
    def approve_request(request_id, approved_by_user):
        """
        Approve a legal access request

        Only SaaS admin should be able to do this
        """
        request = LegalAccessRequest.objects.get(id=request_id)

        if request.status != 'pending':
            raise ValueError(f"Request is not pending (status: {request.status})")

        request.status = 'approved'
        request.approved_by = approved_by_user
        request.approved_at = timezone.now()
        request.save()

        # Log action
        LegalAccessLog.objects.create(
            request=request,
            action='request_approved',
            performed_by=approved_by_user,
            ip_address='0.0.0.0',  # Set from request
            user_agent='System',
            details={'approved_at': request.approved_at.isoformat()}
        )

        return request

    @staticmethod
    def deny_request(request_id, denied_by_user, reason):
        """
        Deny a legal access request
        """
        request = LegalAccessRequest.objects.get(id=request_id)

        request.status = 'denied'
        request.denial_reason = reason
        request.approved_by = denied_by_user
        request.approved_at = timezone.now()
        request.save()

        # Log action
        LegalAccessLog.objects.create(
            request=request,
            action='request_denied',
            performed_by=denied_by_user,
            ip_address='0.0.0.0',
            user_agent='System',
            details={'reason': reason}
        )

        return request

    @staticmethod
    def export_decrypted_messages(request_id, exported_by_user):
        """
        Export decrypted messages for approved legal request

        Creates password-protected ZIP with:
        - Decrypted messages in JSON
        - Metadata
        - Conversation info
        """
        request = LegalAccessRequest.objects.get(id=request_id)

        if request.status != 'approved':
            raise ValueError("Request must be approved before export")

        # Get messages
        messages_query = Message.objects.filter(
            conversation__participants__user=request.target_user,
            is_deleted=False
        )

        # Apply filters
        if request.target_conversation:
            messages_query = messages_query.filter(
                conversation=request.target_conversation
            )

        if request.date_range_start:
            messages_query = messages_query.filter(
                created_at__gte=request.date_range_start
            )

        if request.date_range_end:
            messages_query = messages_query.filter(
                created_at__lte=request.date_range_end
            )

        messages = messages_query.select_related(
            'sender',
            'conversation'
        ).order_by('created_at')

        # Decrypt messages
        export_data = {
            'request_number': request.request_number,
            'target_user': {
                'id': request.target_user.id,
                'username': request.target_user.username,
                'email': request.target_user.email,
            },
            'export_date': timezone.now().isoformat(),
            'conversations': {}
        }

        for message in messages:
            conversation = message.conversation

            # Get conversation key using emergency access
            try:
                # Use master key or reconstruct from encrypted keys
                conversation_key = LegalAccessService._get_conversation_key_emergency(
                    conversation,
                    request.target_user
                )

                # Decrypt message
                decrypted_content = Message.decrypt_message(
                    message.encrypted_content,
                    message.encrypted_iv,
                    conversation_key
                )

                # Add to export
                conv_id = str(conversation.id)
                if conv_id not in export_data['conversations']:
                    export_data['conversations'][conv_id] = {
                        'conversation_id': conversation.id,
                        'conversation_name': conversation.name,
                        'conversation_type': conversation.conversation_type,
                        'messages': []
                    }

                export_data['conversations'][conv_id]['messages'].append({
                    'message_id': message.id,
                    'sender': message.sender.username,
                    'content': decrypted_content,
                    'timestamp': message.created_at.isoformat(),
                    'message_type': message.message_type,
                    'is_edited': message.is_edited,
                })

            except Exception as e:
                # Log decryption failure but continue
                export_data.setdefault('errors', []).append({
                    'message_id': message.id,
                    'error': str(e)
                })

        # Create password-protected ZIP
        password = LegalAccessService._generate_strong_password()

        # Create ZIP in memory
        zip_buffer = io.BytesIO()

        with pyzipper.AESZipFile(
                zip_buffer,
                'w',
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES
        ) as zf:
            zf.setpassword(password.encode())

            # Add JSON data
            json_data = json.dumps(export_data, indent=2)
            zf.writestr('messages.json', json_data)

            # Add metadata
            metadata = {
                'request_number': request.request_number,
                'authority': request.authority_name,
                'export_date': timezone.now().isoformat(),
                'total_messages': sum(
                    len(conv['messages'])
                    for conv in export_data['conversations'].values()
                ),
                'total_conversations': len(export_data['conversations']),
            }
            zf.writestr('metadata.json', json.dumps(metadata, indent=2))

            # Add README
            readme = f"""
LEGAL ACCESS EXPORT
===================

Request Number: {request.request_number}
Authority: {request.authority_name}
Export Date: {timezone.now().isoformat()}

This archive contains decrypted messages as requested by law enforcement.

IMPORTANT:
- This data is confidential and subject to legal restrictions
- Retain until: {request.retention_until}
- Unauthorized access or distribution is prohibited
- All access is logged and monitored

Contents:
- messages.json: Decrypted message content
- metadata.json: Export metadata

Password for this archive has been provided separately.
"""
            zf.writestr('README.txt', readme)

        # Save ZIP file
        zip_buffer.seek(0)
        filename = f"legal_export_{request.request_number}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.zip"

        request.export_file.save(
            filename,
            ContentFile(zip_buffer.getvalue()),
            save=False
        )
        request.export_password = password  # In production, encrypt this!
        request.exported_at = timezone.now()
        request.exported_by = exported_by_user
        request.status = 'fulfilled'
        request.save()

        # Log export
        LegalAccessLog.objects.create(
            request=request,
            action='messages_exported',
            performed_by=exported_by_user,
            ip_address='0.0.0.0',
            user_agent='System',
            details={
                'message_count': sum(
                    len(conv['messages'])
                    for conv in export_data['conversations'].values()
                ),
                'conversation_count': len(export_data['conversations']),
            }
        )

        return request, password

    @staticmethod
    def _get_conversation_key_emergency(conversation, user):
        """
        Emergency access to conversation key

        In production, this would use:
        1. Escrowed master key
        2. Key recovery mechanism
        3. HSM (Hardware Security Module)

        For now, use the standard method
        """
        return EncryptionService.get_conversation_key(conversation, user)

    @staticmethod
    def _generate_strong_password(length=32):
        """Generate strong random password"""
        alphabet = string.ascii_letters + string.digits + string.punctuation
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password

    @staticmethod
    def log_access(request_id, action, user, ip_address, user_agent, details=None):
        """
        Log access to legal request data
        """
        request = LegalAccessRequest.objects.get(id=request_id)
        request.accessed_count += 1
        request.save()

        LegalAccessLog.objects.create(
            request=request,
            action=action,
            performed_by=user,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details or {}
        )
