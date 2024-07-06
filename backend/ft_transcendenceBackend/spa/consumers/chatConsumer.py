import json
from channels.generic.websocket import AsyncWebsocketConsumer
from ..views import extract_user_info_from_token, save_chat_message
from spa.models import CustomUser
from asgiref.sync import sync_to_async
from datetime import datetime, timezone
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer

import asyncio

lock = asyncio.Lock()

global_channel_layer = get_channel_layer()

connected_users = set()
previous_connected_users = set()
print_users_task = None  # Global variable to hold the asyncio task


async def print_connected_users():
    while True:
        async with lock:
            previous_connected_users, current_connected_users = connected_users.copy(), connected_users.copy()
            connected_users.clear()
            # print("Previous connected users:", [user.username for user in previous_connected_users])

        await global_channel_layer.group_send(
            'global',
            {
                'type': 'ping',
                'message': 'PINGING USERS',
            }
        )
        await asyncio.sleep(0.5)
        # print("Current connected users:", [user.username for user in connected_users])

        async with lock:
            disconnected_users = previous_connected_users - connected_users
            # print("Disconnected users:", [user.username for user in disconnected_users])

            for user in disconnected_users:
                user.is_online = False
                user.is_ingame = False
                await database_sync_to_async(user.save)()
                print(f"Set {user.username} offline")


        await asyncio.sleep(3)

class chatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        global print_users_task
        print("CONNECTIONARRR")
        self.user_id, self.username = extract_user_info_from_token(self.scope['session'].get('token'))

        if self.user_id is None or self.username is None:
            await self.close()
            return
        self.userObject = await database_sync_to_async(CustomUser.objects.get)(userid=str(self.user_id))
        self.userObject.is_online = True
        connected_users.add(self.userObject)
        async with lock:
            # self.userObject.online_counter += 1
            # if self.userObject.online_counter == 1:
            self.userObject.is_online = True
            await database_sync_to_async(self.userObject.save)()
        self.room_group_name = 'global'
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        if print_users_task is None:
            print_users_task = asyncio.create_task(print_connected_users())

        await self.send(text_data=json.dumps({
            'type': 'notification',
            'message': 'Connection established.',
            'source_user': self.userObject.username,
            'source_user_id': self.user_id,
        }))

    async def disconnect(self, close_code):
        print("DISCONNECTION")
        # connected_users.remove(self.userObject)
        async with lock:
            # self.userObject.online_counter -= 1
            # if self.userObject.online_counter == 0:
            self.userObject.is_online = False
            self.userObject.is_ingame = False
            await database_sync_to_async(self.userObject.save)()
    
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message")
        timestamp = text_data_json.get("timestamp", datetime.now(timezone.utc).isoformat())
        self.userObject = await sync_to_async(CustomUser.objects.get)(userid=str(self.user_id))

        try:
            user = await sync_to_async(CustomUser.objects.get)(userid=self.user_id)
            self.username = user.username
        except CustomUser.DoesNotExist:
            await self.close()
            return

        if text_data_json.get("type") == 'global.message':
            message_saved = await save_chat_message(self.user_id, None, message, True, timestamp)
            if message_saved:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'global.message',
                        'message': message,
                        'timestamp': timestamp,
                        'source_user': self.userObject.username,
                        'source_user_id': self.user_id,
                    }
                )

        elif text_data_json.get("type") == 'private.message':
            target_user_id = text_data_json.get("target_user_id")
            message_saved = await save_chat_message(self.user_id, target_user_id, message, False, timestamp)
            if message_saved:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'private.message',
                        'message': message,
                        'timestamp': timestamp,
                        'source_user': self.userObject.username,
                        'source_user_id': self.user_id,
                        'target_user_id': target_user_id,
                    }
                )

        elif text_data_json.get("type") == 'pong':
            user_id = text_data_json.get("user_id")
            print(f"PONG RECEIVED from {user_id}")
            try:
                user = await sync_to_async(CustomUser.objects.get)(userid=user_id)
                async with lock:
                    connected_users.add(user)
            except CustomUser.DoesNotExist:
                pass

        elif text_data_json.get("type") == 'game.invite.send':
            target_user_id = text_data_json.get("target_user_id")
            target_user_name = text_data_json.get("target_user_name")
            room_id = text_data_json.get("room_id")
            if target_user_id is not None:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'invitation',
                        'source_user':  self.userObject.username,
                        'source_user_id': self.user_id,
                        'target_user_id': target_user_id,
                        'target_user_name': target_user_name,
                        'room_id': room_id,
                    }
                )

    async def global_message(self, event):
        message = event['message']
        timestamp = event.get('timestamp', datetime.now(timezone.utc).isoformat())
        await self.send(text_data=json.dumps({
            'type': 'global.message',
            'message': message,
            'source_user': event['source_user'],
            'source_user_id': event['source_user_id'],
            'timestamp': timestamp,
        }))

    async def private_message(self, event):
        message = event['message']
        timestamp = event.get('timestamp', datetime.now(timezone.utc).isoformat())
        target_id = event['target_user_id']
        source_id = event['source_user_id']
        if str(target_id) == str(self.user_id) or str(source_id) == str(self.user_id):
            await self.send(text_data=json.dumps({
                'type': 'private.message',
                'message': message,
                'timestamp': timestamp,
                'source_user': event['source_user'],
                'source_user_id': source_id,
                'target_user_id': target_id,
            }))

    async def invitation(self, event):
        target_id = event['target_user_id']
        source_id = event['source_user_id']
        target_user_name = event['target_user_name']
        room_id = event.get('room_id')  # Added to handle room_id

        if str(target_id) == str(self.user_id):
            await self.send(text_data=json.dumps({
                'type': 'game.invite.receive',
                'message': str(source_id) + " has invited you to play.",
                'source_user': event['source_user'],
                'source_user_id': source_id,
                'target_user_id': target_id,
                'target_user_name': target_user_name,
                'room_id': room_id,  # Added room_id
            }))

        if str(source_id) == str(self.user_id):
            await self.send(text_data=json.dumps({
                'type': 'game.invite.send',
                'message': "Invitation successfully sent to " + str(target_user_name),
            }))
    
    async def ping(self, event):
        await self.send(text_data=json.dumps({
            'type': 'ping',
            'message': "PING"
        }))