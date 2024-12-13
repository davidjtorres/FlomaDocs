import redis
from channels.generic.websocket import AsyncWebsocketConsumer
from y_py import YDoc, apply_update, encode_state_as_update
from asgiref.sync import sync_to_async
import logging
from .models import Document

logger = logging.getLogger(__name__)


class DocumentConsumer(AsyncWebsocketConsumer):
    async def connect(self):

        logger.info("Connected")
        self.document_id = self.scope["url_route"]["kwargs"]["document_id"]
        self.room_group_name = f"document_{self.document_id}"
        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        # Initialize Redis connection
        try:
            self.redis_client = redis.StrictRedis(host="redis", port=6379)
        except redis.ConnectionError as e:
            print(e)
            return

        # Initialize YDoc and YText
        self.ydoc = YDoc()
        self.ytext = self.ydoc.get_text("content")

        # Load document state from Redis
        state = await self.get_document_state()
        if state:
            logger.info("state found")
            apply_update(self.ydoc, state)

        # Accept the WebSocket connection
        await self.accept()  # Assuming state is the initial content

        await self.send(bytes_data=encode_state_as_update(self.ydoc))

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, bytes_data):
        # data = json.loads(text_data)
        update = bytes_data

        # size of the update
        logger.info(f"Received update of size {len(update)}")

        # Apply the update to the YDoc
        apply_update(self.ydoc, update)

        # Encode the state
        state = encode_state_as_update(self.ydoc)

        # Save changes to Redis
        await self.save_document_state(state)

        # Broadcast changes to group
        await self.channel_layer.group_send(
            self.room_group_name, {"type": "document_update", "changes": update}
        )

    async def document_update(self, event):
        changes = event["changes"]

        # Send changes to WebSocket
        await self.send(bytes_data=changes)

    @sync_to_async
    def get_document_state(self):
        try:
            state = self.redis_client.get(f"document_state_{self.document_id}")
            if state:
                return state
        except Exception:
            logger.error("Error getting document state from Redis")

    async def save_document_state(self, state):
        try:
            self.redis_client.set(f"document_state_{self.document_id}", state)
        except Exception as e:
            # log error
            logger.error(e)

    @sync_to_async
    def save_document_to_db(self):
        try:
            # Get the document content from YDoc
            content = self.ytext.to_string()

            # Save the document content to the database
            Document.objects.update_or_create(
                id=self.document_id, defaults={"content": content}
            )
            logger.info(f"Document {self.document_id} saved to database")
        except Exception as e:
            logger.error(f"Error saving document to database: {e}")