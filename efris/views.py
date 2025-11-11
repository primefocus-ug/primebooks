from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.generic import View
from .websocket_manager import websocket_manager
from company.models import Company


class EFRISWebSocketStatusView(View):
    """API endpoint for WebSocket status information"""

    @method_decorator(login_required)
    def get(self, request, company_id):
        try:
            # Verify user has access to company
            company = Company.objects.get(pk=company_id)
            if not (company.owner == request.user or
                    request.user in company.users.all() or
                    request.user in company.staff.all()):
                return JsonResponse({'error': 'Access denied'}, status=403)

            # Get connection statistics
            stats = websocket_manager.get_connection_stats(company_id)
            connections = websocket_manager.get_active_connections(company_id)

            return JsonResponse({
                'company_id': company_id,
                'company_name': company.display_name,
                'websocket_stats': stats,
                'active_connections': len(connections),
                'connection_details': [
                    {
                        'user_id': conn.get('user_id'),
                        'connected_at': conn.get('connected_at'),
                        'user_agent': conn.get('user_agent', '')[:100]  # Truncate
                    }
                    for conn in connections[:10]  # Limit to 10 for performance
                ]
            })

        except Company.DoesNotExist:
            return JsonResponse({'error': 'Company not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def test_websocket_broadcast(request, company_id):
    """Test endpoint to broadcast a message via WebSocket"""
    try:
        company = Company.objects.get(pk=company_id)

        # Verify access
        if not (company.owner == request.user or
                request.user in company.users.all() or
                request.user in company.staff.all()):
            return JsonResponse({'error': 'Access denied'}, status=403)

        # Send test notification
        success = websocket_manager.send_notification(
            company_id,
            "Test Message",
            f"Test message sent by {request.user.get_full_name() or request.user.username} at {timezone.now()}",
            "info",
            "normal",
            {'sent_by': request.user.id, 'test': True}
        )

        return JsonResponse({
            'success': success,
            'message': 'Test broadcast sent' if success else 'Failed to send broadcast'
        })

    except Company.DoesNotExist:
        return JsonResponse({'error': 'Company not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


