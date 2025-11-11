from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Max, Count
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
from django.db import models

from .models import (
    Conversation, ConversationParticipant, Message,
    EncryptionKeyManager
)
from .services import EncryptionService

User = get_user_model()


@login_required
def messaging_index(request):
    """
    Main messaging page
    Shows conversation list and chat interface
    """
    # Get user's conversations
    conversations = Conversation.objects.filter(
        participants__user=request.user,
        participants__is_active=True,
        is_active=True
    ).annotate(
        last_message_time=Max('messages__created_at'),
        unread_count=Count(
            'messages',
            filter=Q(
                messages__created_at__gt=models.F('participants__last_read_at'),
                messages__is_deleted=False
            ) & ~Q(messages__sender=request.user)
        )
    ).select_related(
        'created_by'
    ).prefetch_related(
        'participants__user'
    ).order_by('-last_message_time')

    # Get all users for new conversation
    users = User.objects.filter(
        is_active=True
    ).exclude(
        id=request.user.id
    ).order_by('username')

    context = {
        'conversations': conversations,
        'users': users,
        'page_title': 'Messages',
    }

    return render(request, 'messaging/index.html', context)


@login_required
def conversation_detail(request, conversation_id):
    """
    View specific conversation
    """
    conversation = get_object_or_404(
        Conversation,
        id=conversation_id,
        is_active=True
    )

    # Check if user is participant
    participant = ConversationParticipant.objects.filter(
        conversation=conversation,
        user=request.user,
        is_active=True
    ).first()

    if not participant:
        messages.error(request, 'You do not have access to this conversation.')
        return redirect('messaging:index')

    # Get conversation participants
    participants = ConversationParticipant.objects.filter(
        conversation=conversation,
        is_active=True
    ).select_related('user')

    context = {
        'conversation': conversation,
        'participants': participants,
        'current_participant': participant,
        'page_title': conversation.name or 'Direct Message',
    }

    return render(request, 'messaging/conversation_detail.html', context)


@login_required
@require_http_methods(["POST"])
def create_conversation(request):
    """
    Create new conversation via form
    """
    conversation_type = request.POST.get('conversation_type', 'direct')
    name = request.POST.get('name', '')
    description = request.POST.get('description', '')
    participant_ids = request.POST.getlist('participant_ids')

    # Validate
    if not participant_ids:
        messages.error(request, 'Please select at least one participant.')
        return redirect('messaging:index')

    # Check for existing direct conversation
    if conversation_type == 'direct' and len(participant_ids) == 1:
        other_user_id = int(participant_ids[0])

        # Check if direct conversation already exists
        existing = Conversation.objects.filter(
            conversation_type='direct',
            is_active=True,
            participants__user=request.user
        ).filter(
            participants__user_id=other_user_id
        ).first()

        if existing:
            messages.info(request, 'Conversation already exists.')
            return redirect('messaging:conversation_detail', conversation_id=existing.id)

    try:
        # Create conversation
        conversation = Conversation.objects.create(
            conversation_type=conversation_type,
            name=name if conversation_type != 'direct' else '',
            description=description,
            created_by=request.user,
        )

        # Get participant users
        participant_users = list(
            User.objects.filter(id__in=participant_ids)
        )
        participant_users.append(request.user)

        # Initialize encryption
        EncryptionService.create_conversation_with_keys(
            conversation,
            participant_users
        )

        # Create participant records
        import json
        encrypted_keys = json.loads(conversation.encrypted_symmetric_key)

        for user in participant_users:
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=user,
                encrypted_conversation_key=encrypted_keys[str(user.id)],
                is_admin=(user == request.user),
                can_add_participants=(user == request.user),
                can_remove_participants=(user == request.user)
            )

        messages.success(request, 'Conversation created successfully!')
        return redirect('messaging:conversation_detail', conversation_id=conversation.id)

    except Exception as e:
        messages.error(request, f'Error creating conversation: {str(e)}')
        return redirect('messaging:index')


@login_required
@require_http_methods(["GET"])
def user_search(request):
    """
    Search users for adding to conversation
    AJAX endpoint
    """
    query = request.GET.get('q', '')

    if len(query) < 2:
        return JsonResponse({'users': []})

    users = User.objects.filter(
        Q(username__icontains=query) |
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(email__icontains=query),
        is_active=True
    ).exclude(
        id=request.user.id
    ).values(
        'id', 'username', 'first_name', 'last_name', 'email'
    )[:10]

    return JsonResponse({
        'users': list(users)
    })


@login_required
@require_http_methods(["POST"])
def mark_all_read(request, conversation_id):
    """
    Mark all messages in conversation as read
    """
    conversation = get_object_or_404(Conversation, id=conversation_id)

    # Check access
    participant = ConversationParticipant.objects.filter(
        conversation=conversation,
        user=request.user,
        is_active=True
    ).first()

    if not participant:
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Update last_read_at
    from django.utils import timezone
    participant.last_read_at = timezone.now()
    participant.save()

    return JsonResponse({'success': True})


@login_required
def notifications_count(request):
    """
    Get unread message count
    AJAX endpoint for navbar badge
    """
    unread_count = Message.objects.filter(
        conversation__participants__user=request.user,
        conversation__participants__is_active=True,
        is_deleted=False
    ).exclude(
        sender=request.user
    ).exclude(
        read_receipts__user=request.user
    ).count()

    return JsonResponse({
        'count': unread_count
    })

