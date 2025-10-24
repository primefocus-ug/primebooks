import json
from channels.generic.websocket import AsyncWebsocketConsumer

class CompanyConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("stores_updates", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("stores_updates", self.channel_name)

    async def store_update(self, event):
        await self.send(text_data=json.dumps(event["data"]))
