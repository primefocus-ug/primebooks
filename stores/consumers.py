import json
from channels.generic.websocket import AsyncWebsocketConsumer


class CompanyConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for company-scoped store update events.

    FIXES applied:
    1. Authentication check — anonymous connections are rejected immediately.
    2. Tenant/company scoping — each connection joins a company-specific
       group rather than the global "stores_updates" group.  Without this,
       every connected client across ALL companies would receive every store
       update, leaking data across tenant boundaries.
    3. Group name sanitisation — Django Channels group names must be valid
       ASCII identifiers; the company PK (an integer) satisfies this.
    """

    async def connect(self):
        # FIX 1: Reject unauthenticated connections immediately.
        # Without this check, any anonymous WebSocket client could connect
        # and receive real-time store events.
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close()
            return

        # FIX 2: Scope the group to this user's company so updates from one
        # tenant are never broadcast to another tenant's clients.
        # The old code used the hardcoded group name "stores_updates" which
        # meant ALL companies shared the same channel group.
        company_id = getattr(getattr(user, "company", None), "id", None)
        if not company_id:
            # User has no company — nothing meaningful to subscribe to.
            await self.close()
            return

        self.group_name = f"stores_updates_{company_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # Only discard if we actually joined a group (connect may have closed early).
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def store_update(self, event):
        await self.send(text_data=json.dumps(event["data"]))