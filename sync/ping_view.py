"""
sync/ping_view.py
=================
GET /api/v1/sync/ping/

Used by the desktop SyncEngine every 30 seconds to check connectivity
and decide whether to attempt a sync. Must be extremely fast — no DB hits.

Response:
  200  {"status": "ok", "server_time": 1234567890.123, "schema": "rem"}
  401  (unauthenticated — JWT expired)
"""

import time
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sync_ping(request):
    schema_name = ""
    if hasattr(request, "tenant"):
        schema_name = request.tenant.schema_name

    return Response({
        "status":      "ok",
        "server_time": time.time(),
        "schema":      schema_name,
        "user":        request.user.email,
    })