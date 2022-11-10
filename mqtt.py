import base64 as b64
import json
import asyncio_mqtt as aiomqtt
from aiostream import stream
import logging
from decouple import config
import asyncio
import time

MQTT_BROKER = config('MQTT_BROKER')
MQTT_RECONNECT_INTERVAL = config('MQTT_RECONNECT_INTERVAL', default=5)
MQTT_TOPIC_PICTURE = config('MQTT_TOPIC_PICTURE', default='arlo/picture')
# MQTT_TOPIC_LOCATION = config('MQTT_TOPIC_LOCATION', default='arlo/location')
MQTT_TOPIC_CONTROL = config('MQTT_TOPIC_CONTROL',
                            default='arlo/control/{name}')
MQTT_TOPIC_STATUS = config('MQTT_TOPIC_STATUS', default='arlo/status/{name}')


async def mqtt_client(cameras):
    """
    Async mqtt client, initiaties various generators and readers
    """
    while True:
        try:
            async with aiomqtt.Client(MQTT_BROKER) as client:
                logging.info(f"MQTT client connected to {MQTT_BROKER}")
                await asyncio.gather(
                    # Generators/Readers
                    pic_streamer(client, cameras),
                    mqtt_reader(client, cameras),
                    device_status(client, cameras)
                    )
        except aiomqtt.MqttError as error:
            logging.info(f'MQTT "{error}". reconnecting.')
            await asyncio.sleep(MQTT_RECONNECT_INTERVAL)


async def pic_streamer(client, cameras):
    """
    Merge picture streams from all cameras and publish to MQTT
    """
    pics = stream.merge(*[c.get_pictures() for c in cameras])
    async with pics.stream() as streamer:
        async for name, data in streamer:
            timestamp = str(time.time()).replace(".", "")
            await client.publish(
                MQTT_TOPIC_PICTURE.format(name=name),
                payload=json.dumps({
                    "filename": f"{timestamp} {name}.jpg",
                    "payload": b64.b64encode(data).decode("utf-8")
                    }))


async def device_status(client, cameras):
    """
    Merge device statuss from all cameras and publish to MQTT
    """
    statuses = stream.merge(*[c.listen_status() for c in cameras])
    async with statuses.stream() as streamer:
        async for name, status in streamer:
            await client.publish(
                MQTT_TOPIC_STATUS.format(name=name),
                payload=json.dumps(status)
                )


async def mqtt_reader(client, cameras):
    """
    Subscribe to control topics, and pass messages to individual cameras
    """
    cams = {MQTT_TOPIC_CONTROL.format(name=c.name): c for c in cameras}
    async with client.unfiltered_messages() as messages:
        for name, _ in cams.items():
            await client.subscribe(name)
        async for message in messages:
            if message.topic in cams:
                asyncio.create_task(cams[message.topic].mqtt_control(
                    message.payload.decode("utf-8")))
