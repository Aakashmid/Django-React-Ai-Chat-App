from channels.generic.websocket import AsyncWebsocketConsumer
from .serializers import MessageSerializer, MessageSerilizerForChatHistory
from asgiref.sync import sync_to_async
import json
from .models import Message, Conversation
import asyncio
from openai import OpenAI
from decouple import config


from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

endpoint = "https://models.github.ai/inference"
model_name = "openai/gpt-4.1"
token = config("GITHUB_TOKEN")


client = ChatCompletionsClient(
    endpoint=endpoint,
    credential=AzureKeyCredential(token),
)


conversation_histories = {}  # for conversation history for remembering the chat for ai
stop_flags = {}  # for cross-instance signaling


async def get_question_response(request_question, token):  # token is unique for each conversation
    if token not in conversation_histories:
        #  ("New conversation started")
        conversation_histories[token] = []
        messages = await get_conversation_message(token)
        if messages:
            #  print("Messages found in the database")
            conversation_histories[token].extend(messages)

    conversation_histories[token].append(UserMessage(request_question))

    messages = [SystemMessage("You are a helpful assistant.")] + conversation_histories[token]

    # return response in streaming format
    response = await client.complete(messages=messages, temperature=1.0, top_p=1.0, max_tokens=1000, model=model_name, stream=True)

    async for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            yield content


# to check whether the conversation exists or not
@sync_to_async(thread_sensitive=True)
def get_conversation_message(token):
    try:
        messages = Message.objects.filter(conversation__token=token).order_by('timestamp').values('request_text', 'response_text')
        serialized_messages = MessageSerilizerForChatHistory(messages, many=True).data
        # Flatten the list of lists
        flattened_messages = [{"role": "user", "content": message["request_text"]} for message in serialized_messages] + [
            {"role": "system", "content": message["response_text"]} for message in serialized_messages
        ]
        return flattened_messages

    except Exception as e:
        print(f"Error fetching messages: {e}")
        return []


@sync_to_async
def get_conversation(token):
    try:
        return Conversation.objects.get(token=token)
    except Conversation.DoesNotExist:
        return None


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['conversation_token']
        self.room_group_name = f'chat_{self.room_name}'
        self.stop_event = asyncio.Event()
        self.streaming_task = None  # Task for streaming

        conversation = await get_conversation(self.room_name)
        if not conversation:
            await self.send(text_data=json.dumps({'error': 'Invalid conversation token'}))
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.streaming_task and not self.streaming_task.done():
            self.streaming_task.cancel()
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type')

        if message_type == 'stop_streaming':
            self.stop_event.set()
            return

        if message_type == 'start_streaming':
            request_text = text_data_json.get('request_text')
            if request_text:
                self.stop_event.clear()
                # Start streaming in a separate task
                self.streaming_task = asyncio.create_task(self.stream_response(request_text))

    async def stream_response(self, request_text):
        await self.send(text_data=json.dumps({'request_text': request_text, 'type': 'request_text'}))
        response_text = ""

        try:
            async for chunk in get_question_response(request_text, self.room_name):
                if self.stop_event.is_set():
                    await self.send(json.dumps({'type': 'streaming_stopped', 'message': 'Streaming stopped by user.'}))
                    self.stop_event.clear()
                    break

                response_text += chunk
                await self.send(text_data=json.dumps({'response_text': chunk, 'type': 'response_chunk'}))
                await asyncio.sleep(0)

            await self.send(text_data=json.dumps({'response_text': response_text, 'type': 'response_complete'}))

            if response_text:
                await self.save_message(request_text, response_text, conversation_token=self.room_name)

        except asyncio.CancelledError:
            await self.send(json.dumps({'type': 'streaming_stopped', 'message': 'Streaming cancelled.'}))
        except Exception as e:
            response_error = "Sorry, an error occurred while processing your request."
            print(f"Error getting response: {e}")
            await self.send(text_data=json.dumps({'message': response_error, 'type': 'error'}))

    @sync_to_async
    def save_message(self, request_text, response_text, conversation_token):
        try:
            conversation = Conversation.objects.get(token=conversation_token)
            Message.objects.create(conversation=conversation, request_text=request_text, response_text=response_text)
        except Conversation.DoesNotExist:
            raise ValueError('Conversation not found')
        except Exception as e:
            raise ValueError(f'Error saving message: {str(e)}')
