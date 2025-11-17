from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from django.conf import settings
from django.core.cache import cache
from django_tenants.utils import schema_context, get_tenant_model
from .models import EncryptionKeyManager, ConversationParticipant
import os
import base64
import json
import logging

logger = logging.getLogger(__name__)


class EncryptionService:
    @staticmethod
    def generate_user_keys(user):
        # Generate keys
        private_pem, public_pem = EncryptionKeyManager.generate_rsa_keys()

        # Encrypt private key with derived password
        encrypted_private = EncryptionService._encrypt_private_key(
            private_pem,
            user
        )

        # Save to database (in current tenant schema)
        key_manager, created = EncryptionKeyManager.objects.update_or_create(
            user=user,
            defaults={
                'public_key': public_pem,
                'encrypted_private_key': encrypted_private,
                'key_version': 1
            }
        )

        logger.info(f"Generated encryption keys for user {user.id} in tenant")
        return key_manager

    @staticmethod
    def _encrypt_private_key(private_pem, user):
        password_bytes = user.password.encode('utf-8')

        # Use user-specific salt for better security
        salt = f'messaging_salt_{user.id}'.encode('utf-8')

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        derived_key = kdf.derive(password_bytes)

        iv = os.urandom(16)
        cipher = Cipher(
            algorithms.AES(derived_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()

        private_bytes = private_pem.encode('utf-8')
        padding_length = 16 - (len(private_bytes) % 16)
        padded = private_bytes + bytes([padding_length] * padding_length)

        encrypted = encryptor.update(padded) + encryptor.finalize()

        combined = iv + encrypted
        return base64.b64encode(combined).decode()

    @staticmethod
    def _decrypt_private_key(encrypted_private, user):
        """
        Decrypt user's private key
        Returns: private_pem string
        """
        password_bytes = user.password.encode('utf-8')
        salt = f'messaging_salt_{user.id}'.encode('utf-8')

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        derived_key = kdf.derive(password_bytes)

        combined = base64.b64decode(encrypted_private)
        iv = combined[:16]
        encrypted = combined[16:]

        cipher = Cipher(
            algorithms.AES(derived_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()

        decrypted_padded = decryptor.update(encrypted) + decryptor.finalize()
        padding_length = decrypted_padded[-1]
        decrypted = decrypted_padded[:-padding_length]

        return decrypted.decode('utf-8')

    @staticmethod
    def get_user_private_key(user, schema_name=None):
        """
        Load user's private key object from encrypted storage

        TENANT-AWARE: Can fetch keys from specific tenant
        Returns: RSA private key object
        """

        def _get_key():
            try:
                key_manager = user.encryption_keys
            except EncryptionKeyManager.DoesNotExist:
                key_manager = EncryptionService.generate_user_keys(user)

            private_pem = EncryptionService._decrypt_private_key(
                key_manager.encrypted_private_key,
                user
            )

            return serialization.load_pem_private_key(
                private_pem.encode(),
                password=None,
                backend=default_backend()
            )

        # If schema specified, use it (for cross-tenant)
        if schema_name:
            with schema_context(schema_name):
                return _get_key()
        else:
            return _get_key()

    @staticmethod
    def get_conversation_key(conversation, user):
        """
        Decrypt conversation's symmetric key for user

        TENANT-AWARE: Works within tenant boundaries
        Returns: bytes (32 bytes AES-256 key)
        """
        # Check cache first
        cache_key = f'conv_key_{conversation.id}_{user.id}'
        cached_key = cache.get(cache_key)
        if cached_key:
            return base64.b64decode(cached_key)

        # Get participant record
        try:
            participant = ConversationParticipant.objects.get(
                conversation=conversation,
                user=user,
                is_active=True
            )
        except ConversationParticipant.DoesNotExist:
            raise PermissionError(f"User {user.id} not in conversation {conversation.id}")

        # Get user's private key
        private_key = EncryptionService.get_user_private_key(user)

        # Decrypt conversation key
        encrypted_key = base64.b64decode(participant.encrypted_conversation_key)

        conversation_key = private_key.decrypt(
            encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # Cache for 1 hour
        cache.set(cache_key, base64.b64encode(conversation_key).decode(), 3600)

        return conversation_key

    @staticmethod
    def encrypt_message_content(content, conversation_key):
        """
        Encrypt message content with conversation's symmetric key
        Returns: (encrypted_content, iv)
        """
        from .models import Message
        return Message.encrypt_message(content, conversation_key)

    @staticmethod
    def decrypt_message_content(encrypted_content, iv, conversation_key):
        """
        Decrypt message content
        Returns: plaintext string
        """
        from .models import Message
        return Message.decrypt_message(encrypted_content, iv, conversation_key)

    @staticmethod
    def encrypt_file(file_data, conversation_key):
        """
        Encrypt file data
        Returns: (encrypted_data, iv)
        """
        iv = os.urandom(16)

        cipher = Cipher(
            algorithms.AES(conversation_key),
            modes.CBC(iv),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()

        padding_length = 16 - (len(file_data) % 16)
        padded_data = file_data + bytes([padding_length] * padding_length)

        encrypted = encryptor.update(padded_data) + encryptor.finalize()

        return encrypted, base64.b64encode(iv).decode()

    @staticmethod
    def decrypt_file(encrypted_data, iv, conversation_key):
        """
        Decrypt file data
        Returns: bytes
        """
        iv_bytes = base64.b64decode(iv)

        cipher = Cipher(
            algorithms.AES(conversation_key),
            modes.CBC(iv_bytes),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()

        decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
        padding_length = decrypted_padded[-1]
        decrypted = decrypted_padded[:-padding_length]

        return decrypted

    @staticmethod
    def encrypt_metadata(data, conversation_key):
        """
        Encrypt metadata (filename, size, etc.)
        Returns: (encrypted_data, iv)
        """
        return EncryptionService.encrypt_message_content(
            str(data),
            conversation_key
        )

    @staticmethod
    def decrypt_metadata(encrypted_data, iv, conversation_key):
        """
        Decrypt metadata
        Returns: string
        """
        return EncryptionService.decrypt_message_content(
            encrypted_data,
            iv,
            conversation_key
        )

    @staticmethod
    def create_conversation_with_keys(conversation, participants):
        """
        Initialize conversation with encrypted keys for all participants

        TENANT-AWARE: Handles cross-tenant conversations for SaaS admin

        Args:
            conversation: Conversation instance
            participants: List of User instances

        Returns: conversation instance
        """
        # Generate conversation symmetric key
        symmetric_key = conversation.generate_symmetric_key()

        # Encrypt for each participant
        encrypted_keys = {}
        tenant_schemas = set()

        for user in participants:
            # Track tenant schemas for cross-tenant conversations
            if hasattr(user.company, 'schema_name'):
                tenant_schemas.add(user.company.schema_name)

            # Ensure user has encryption keys
            try:
                key_manager = user.encryption_keys
            except EncryptionKeyManager.DoesNotExist:
                key_manager = EncryptionService.generate_user_keys(user)

            # Encrypt conversation key with user's public key
            encrypted_key = conversation.encrypt_key_for_user(symmetric_key, user)
            encrypted_keys[user.id] = encrypted_key

        # Store encrypted keys in conversation
        conversation.encrypted_symmetric_key = json.dumps(encrypted_keys)

        # Store tenant schemas if cross-tenant
        if conversation.is_cross_tenant and len(tenant_schemas) > 1:
            conversation.tenant_schemas = list(tenant_schemas)

        conversation.save()

        logger.info(f"Created conversation {conversation.id} with {len(participants)} participants")
        return conversation

    @staticmethod
    def add_participant_keys(conversation, new_user):
        """
        Add encryption keys for a new participant

        TENANT-AWARE: Works with cross-tenant conversations
        Updates conversation's encrypted_symmetric_key
        """
        # Get existing keys
        encrypted_keys = json.loads(conversation.encrypted_symmetric_key)

        # Get conversation key from existing participant
        existing_participant = conversation.participants.filter(is_active=True).first()
        if not existing_participant:
            raise ValueError("No existing participants to get key from")

        # Decrypt conversation key
        conversation_key = EncryptionService.get_conversation_key(
            conversation,
            existing_participant.user
        )

        # Ensure new user has encryption keys
        try:
            key_manager = new_user.encryption_keys
        except EncryptionKeyManager.DoesNotExist:
            key_manager = EncryptionService.generate_user_keys(new_user)

        # Encrypt for new user
        encrypted_key = conversation.encrypt_key_for_user(conversation_key, new_user)
        encrypted_keys[str(new_user.id)] = encrypted_key

        # Update conversation
        conversation.encrypted_symmetric_key = json.dumps(encrypted_keys)

        # Update tenant schemas if cross-tenant
        if conversation.is_cross_tenant and hasattr(new_user.company, 'schema_name'):
            if new_user.company.schema_name not in conversation.tenant_schemas:
                conversation.tenant_schemas.append(new_user.company.schema_name)

        conversation.save()

        logger.info(f"Added user {new_user.id} to conversation {conversation.id}")
        return encrypted_key


class MessageIntegrityService:
    """
    Service for message integrity verification
    """

    @staticmethod
    def calculate_hash(content):
        """Calculate SHA-256 hash of message content"""
        from .models import Message
        return Message.calculate_hash(content)

    @staticmethod
    def verify_message(message, decrypted_content):
        """
        Verify message hasn't been tampered with
        Returns: bool
        """
        calculated_hash = MessageIntegrityService.calculate_hash(decrypted_content)
        return calculated_hash == message.message_hash

    @staticmethod
    def detect_tampering(message, conversation_key):
        """
        Check if message has been tampered with
        Returns: (is_valid, decrypted_content)
        """
        try:
            decrypted = EncryptionService.decrypt_message_content(
                message.encrypted_content,
                message.encrypted_iv,
                conversation_key
            )

            is_valid = MessageIntegrityService.verify_message(message, decrypted)

            return is_valid, decrypted

        except Exception as e:
            logger.error(f"Tampering detection failed for message {message.id}: {e}")
            return False, None


class TenantMessagingService:
    @staticmethod
    def can_create_cross_tenant_conversation(user):
        return getattr(user, 'is_saas_admin', False)

    @staticmethod
    def get_user_conversations(user, include_archived=False):
        from .models import Conversation, ConversationParticipant

        queryset = Conversation.objects.filter(
            participants__user=user,
            participants__is_active=True,
            is_active=True
        )

        if not include_archived:
            queryset = queryset.filter(archived_at__isnull=True)

        return queryset.distinct()

    @staticmethod
    def search_users_for_conversation(search_term, current_user, limit=20):
        from django.contrib.auth import get_user_model
        from django.db.models import Q

        User = get_user_model()

        queryset = User.objects.filter(
            Q(username__icontains=search_term) |
            Q(first_name__icontains=search_term) |
            Q(last_name__icontains=search_term) |
            Q(email__icontains=search_term),
            is_active=True
        ).exclude(id=current_user.id)

        # Exclude hidden users unless current user is SaaS admin
        if not getattr(current_user, 'is_saas_admin', False):
            queryset = queryset.filter(is_hidden=False)

        return queryset[:limit]