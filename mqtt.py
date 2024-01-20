import base64 as b64
import json
import aiomqtt
from aiostream import stream
import logging
from decouple import config
import asyncio
import time

DEBUG = config('DEBUG', default=False, cast=bool)
MQTT_BROKER = config('MQTT_BROKER')
MQTT_PORT = config('MQTT_PORT', cast=int, default=1883)
MQTT_USER = config('MQTT_USER', default=None)
MQTT_PASS = config('MQTT_PASS', default=None)
MQTT_RECONNECT_INTERVAL = config('MQTT_RECONNECT_INTERVAL', default=5)
MQTT_TOPIC_PICTURE = config('MQTT_TOPIC_PICTURE', default='arlo/picture')
# MQTT_TOPIC_LOCATION = config('MQTT_TOPIC_LOCATION', default='arlo/location')
MQTT_TOPIC_CONTROL = config('MQTT_TOPIC_CONTROL',
                            default='arlo/control/{name}')
MQTT_TOPIC_STATUS = config('MQTT_TOPIC_STATUS', default='arlo/status/{name}')
MQTT_TOPIC_MOTION = config('MQTT_TOPIC_MOTION', default='arlo/motion/{name}')

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


async def mqtt_client(cameras, bases):
    """
    Async mqtt client, initiaties various generators and readers
    """
    while True:
        try:
            async with aiomqtt.Client(
                hostname=MQTT_BROKER,
                port=MQTT_PORT,
                username=MQTT_USER,
                password=MQTT_PASS
            ) as client:
                logging.info(f"MQTT client connected to {MQTT_BROKER}")
                await asyncio.gather(
                    # Generators/Readers
                    mqtt_reader(client, cameras + bases),
                    device_status(client, cameras + bases),
                    motion_stream(client, cameras),
                    pic_streamer(client, cameras)
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


async def device_status(client, devices):
    """
    Merge device status from all devices and publish to MQTT
    """
    statuses = stream.merge(*[d.listen_status() for d in devices])
    async with statuses.stream() as streamer:
        async for name, status in streamer:
            await client.publish(
                MQTT_TOPIC_STATUS.format(name=name),
                payload=json.dumps(status)
                )


async def motion_stream(client, cameras):
    """
    Merge motion events from all cameras and publish to MQTT
    """
    motion_states = stream.merge(*[c.listen_motion() for c in cameras])
    async with motion_states.stream() as streamer:
        async for name, motion in streamer:
            await client.publish(
                MQTT_TOPIC_MOTION.format(name=name),
                payload=json.dumps(motion)
                )


async def mqtt_reader(client, devices):
    """
    Subscribe to control topics, and pass messages to individual cameras
    """
    devs = {MQTT_TOPIC_CONTROL.format(name=d.name): d for d in devices}
    async with client.messages() as messages:
        for name, _ in devs.items():
            await client.subscribe(name)
        async for message in messages:
            if message.topic.value in devs:
                asyncio.create_task(devs[message.topic.value].mqtt_control(
                    message.payload.decode("utf-8")))
