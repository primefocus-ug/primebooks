# messaging/management/commands/diagnose_messaging.py
from django.core.management.base import BaseCommand
from messaging.models import Conversation, ConversationParticipant, EncryptionKeyManager
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Diagnose messaging setup and fix common issues'

    def add_arguments(self, parser):
        parser.add_argument('--user-id', type=int, help='User ID to diagnose')
        parser.add_argument('--conversation-id', type=int, help='Conversation ID to diagnose')
        parser.add_argument('--fix', action='store_true', help='Attempt to fix issues')

    def handle(self, *args, **options):
        user_id = options.get('user_id')
        conversation_id = options.get('conversation_id')
        should_fix = options.get('fix')

        if user_id:
            self.diagnose_user(user_id, should_fix)

        if conversation_id:
            self.diagnose_conversation(conversation_id, should_fix)

        if not user_id and not conversation_id:
            self.general_diagnosis(should_fix)

    def diagnose_user(self, user_id, should_fix):
        self.stdout.write(self.style.HTTP_INFO(f'\n=== Diagnosing User {user_id} ==='))

        try:
            user = User.objects.get(id=user_id)
            self.stdout.write(f'Username: {user.username}')
            self.stdout.write(f'Email: {user.email}')
            self.stdout.write(f'Is active: {user.is_active}')

            # Check encryption keys
            has_keys = hasattr(user, 'encryption_keys')
            self.stdout.write(f'Has encryption keys: {has_keys}')

            if not has_keys and should_fix:
                from messaging.services import EncryptionService
                EncryptionService.generate_user_keys(user)
                self.stdout.write(self.style.SUCCESS('✓ Generated encryption keys'))

            # Check conversations
            conversations = ConversationParticipant.objects.filter(user=user)
            self.stdout.write(f'Participant in {conversations.count()} conversation(s)')

            for participant in conversations:
                self.stdout.write(f'\n  Conversation {participant.conversation_id}:')
                self.stdout.write(f'    - Can send messages: {participant.can_send_messages}')
                self.stdout.write(f'    - Is active: {participant.is_active}')
                self.stdout.write(f'    - Is admin: {participant.is_admin}')

                if not participant.can_send_messages and should_fix:
                    participant.can_send_messages = True
                    participant.save()
                    self.stdout.write(self.style.SUCCESS('    ✓ Fixed: Enabled can_send_messages'))

        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User {user_id} not found'))

    def diagnose_conversation(self, conversation_id, should_fix):
        self.stdout.write(self.style.HTTP_INFO(f'\n=== Diagnosing Conversation {conversation_id} ==='))

        try:
            conversation = Conversation.objects.get(id=conversation_id)
            self.stdout.write(f'Type: {conversation.conversation_type}')
            self.stdout.write(f'Name: {conversation.name or "[No name]"}')
            self.stdout.write(f'Is active: {conversation.is_active}')

            # Check participants
            participants = conversation.participants.all()
            self.stdout.write(f'Participants: {participants.count()}')

            issues_found = False
            for participant in participants:
                self.stdout.write(f'\n  {participant.user.username}:')
                self.stdout.write(f'    - Can send: {participant.can_send_messages}')
                self.stdout.write(f'    - Active: {participant.is_active}')
                self.stdout.write(f'    - Admin: {participant.is_admin}')

                if not participant.can_send_messages:
                    issues_found = True
                    if should_fix:
                        participant.can_send_messages = True
                        participant.save()
                        self.stdout.write(self.style.SUCCESS('    ✓ Fixed: Enabled can_send_messages'))
                    else:
                        self.stdout.write(self.style.WARNING('    ⚠ Issue: Cannot send messages'))

                if not participant.is_active:
                    issues_found = True
                    self.stdout.write(self.style.WARNING('    ⚠ Issue: Participant not active'))

                # Check encryption keys
                has_keys = hasattr(participant.user, 'encryption_keys')
                if not has_keys:
                    issues_found = True
                    if should_fix:
                        from messaging.services import EncryptionService
                        EncryptionService.generate_user_keys(participant.user)
                        self.stdout.write(self.style.SUCCESS('    ✓ Fixed: Generated encryption keys'))
                    else:
                        self.stdout.write(self.style.WARNING('    ⚠ Issue: No encryption keys'))

            if not issues_found:
                self.stdout.write(self.style.SUCCESS('\n✓ No issues found'))

        except Conversation.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Conversation {conversation_id} not found'))

    def general_diagnosis(self, should_fix):
        self.stdout.write(self.style.HTTP_INFO('\n=== General Diagnosis ==='))

        # Check users
        users = User.objects.filter(is_active=True)
        self.stdout.write(f'Active users: {users.count()}')

        users_without_keys = 0
        for user in users:
            if not hasattr(user, 'encryption_keys'):
                users_without_keys += 1
                if should_fix:
                    from messaging.services import EncryptionService
                    EncryptionService.generate_user_keys(user)

        if users_without_keys > 0:
            if should_fix:
                self.stdout.write(self.style.SUCCESS(f'✓ Generated keys for {users_without_keys} users'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠ {users_without_keys} users without encryption keys'))

        # Check conversations
        conversations = Conversation.objects.filter(is_active=True)
        self.stdout.write(f'Active conversations: {conversations.count()}')

        # Check participants with issues
        participants_no_send = ConversationParticipant.objects.filter(
            is_active=True,
            can_send_messages=False
        )
        if participants_no_send.count() > 0:
            self.stdout.write(self.style.WARNING(f'⚠ {participants_no_send.count()} active participants cannot send messages'))
            if should_fix:
                participants_no_send.update(can_send_messages=True)
                self.stdout.write(self.style.SUCCESS(f'✓ Fixed {participants_no_send.count()} participants'))

        self.stdout.write(self.style.SUCCESS('\n✓ Diagnosis complete'))
        if not should_fix:
            self.stdout.write(self.style.HTTP_INFO('\nRun with --fix to attempt automatic fixes'))