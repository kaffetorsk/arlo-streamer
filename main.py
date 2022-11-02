from decouple import config
import pyaarlo
import asyncio
import logging
import signal
from camera import Camera
import base64 as b64
import json
import asyncio_mqtt as aiomqtt
from aiostream import stream

ARLO_USER = config('ARLO_USER')
ARLO_PASS = config('ARLO_PASS')
IMAP_HOST = config('IMAP_HOST')
IMAP_USER = config('IMAP_USER')
IMAP_PASS = config('IMAP_PASS')
MQTT_BROKER = config('MQTT_BROKER')
MQTT_RECONNECT_INTERVAL = config('MQTT_RECONNECT_INTERVAL', default=5)
MQTT_TOPIC_PICTURE = config('MQTT_TOPIC_PICTURE', default='arlo/picture')
MQTT_TOPIC_LOCATION = config('MQTT_TOPIC_LOCATION', default='arlo/location')
MQTT_TOPIC_CONTROL = config('MQTT_TOPIC_CONTROL', default='arlo/control/{name}')
FFMPEG_OUT = config('FFMPEG_OUT')
MOTION_TIMEOUT = config('MOTION_TIMEOUT', default=60, cast=int)
ARLO_REFRESH = config('ARLO_REFRESH', default=3600, cast=int)
DEBUG = config('DEBUG', default=False, cast=bool)


logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )


async def main():
    # login with 2FA
    arlo = pyaarlo.PyArlo(
        username=ARLO_USER, password=ARLO_PASS,
        tfa_source='imap', tfa_type='email',
        tfa_host=IMAP_HOST, tfa_username=IMAP_USER, tfa_password=IMAP_PASS
        )

    cameras = [Camera(c, FFMPEG_OUT, MOTION_TIMEOUT) for c in arlo.cameras]
    camera_tasks = [asyncio.create_task(c.run()) for c in cameras]

    async def mqtt_client():
        while True:
            try:
                async with aiomqtt.Client(MQTT_BROKER) as client:
                    logging.info(f"MQTT client connected to {MQTT_BROKER}")

                    async def pic_streamer():
                        pics = stream.merge(*[c.get_pictures() for c in cameras])
                        async with pics.stream() as streamer:
                            async for name, data in streamer:
                                await client.publish(
                                    MQTT_TOPIC_PICTURE.format(name=name),
                                    payload=json.dumps({
                                        "filename": "test.jpg",
                                        "payload": b64.b64encode(data).decode("utf-8")
                                        }))

                    async def mqtt_reader():
                        cams = {MQTT_TOPIC_CONTROL.format(name=c.name): c for c in cameras}
                        print(cams)
                        async with client.unfiltered_messages() as messages:
                            for name, _ in cams.items():
                                await client.subscribe(name)
                            async for message in messages:
                                print(message.topic)
                                if message.topic in cams:
                                    print(message.payload)
                                    await cams[name].mqtt_control(
                                        message.payload.decode("utf-8"))

                    await asyncio.gather(pic_streamer(), mqtt_reader())
            except aiomqtt.MqttError as error:
                logging.info(f'MQTT "{error}". reconnecting.')
                await asyncio.sleep(MQTT_RECONNECT_INTERVAL)

    # Graceful shutdown
    def shutdown(signal, frame):
        logging.info('Shutting down...')
        for c in cameras:
            # c.shutdown(signal)
            # mqtt_client.loop_stop()
            asyncio.get_running_loop().stop()

    # Register callbacks for shutdown
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    await asyncio.gather(*camera_tasks, mqtt_client())

    # await asyncio.sleep(ARLO_REFRESH)

while True:
    try:
        asyncio.run(main())
        logging.info("Refreshing")
    except RuntimeError:
        logging.info("Closed.")
        break
