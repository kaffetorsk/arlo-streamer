from decouple import config
import pyaarlo
import asyncio
import logging
import signal
import paho.mqtt.client as mqtt
from camera import Camera
import base64
import json
import time

ARLO_USER = config('ARLO_USER')
ARLO_PASS = config('ARLO_PASS')
IMAP_HOST = config('IMAP_HOST')
IMAP_USER = config('IMAP_USER')
IMAP_PASS = config('IMAP_PASS')
MQTT_BROKER = config('MQTT_BROKER')
MQTT_TOPIC_PICTURE = config('MQTT_TOPIC_PICTURE', default='arlo/picture')
MQTT_TOPIC_LOCATION = config('MQTT_TOPIC_LOCATION', default='arlo/location')
FFMPEG_OUT = config('FFMPEG_OUT')
MOTION_TIMEOUT = config('MOTION_TIMEOUT', default=60, cast=int)
ARLO_REFRESH = config('ARLO_REFRESH', default=3600, cast=int)
DEBUG=config('DEBUG', default=False, cast=bool)


logging.basicConfig(
    level = logging.DEBUG if DEBUG else logging.INFO,
    format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )


async def main():
    # login with 2FA
    arlo = pyaarlo.PyArlo(username=ARLO_USER, password=ARLO_PASS,
                        tfa_source='imap',tfa_type='email',
                        tfa_host=IMAP_HOST,
                        tfa_username=IMAP_USER,
                        tfa_password=IMAP_PASS
                        )

    mqtt_client = mqtt.Client()
    mqtt_client.connect_async(MQTT_BROKER, 1883, 60)
    mqtt_client.loop_start()
    #mqtt_thread = asyncio.get_running_loop().run_in_executor(None, mqtt_client.loop_forever)

    def callback_picture(picture, name):
        topic = MQTT_TOPIC_PICTURE.format(name=name)
        logging.info("mqtt // picture sent on topic: " + MQTT_TOPIC_PICTURE )
        mqtt_client.publish(
            MQTT_TOPIC_PICTURE,
            json.dumps({
                "filename": "test.jpg",
                "payload": base64.b64encode(picture).decode("utf-8")
            })
        )

    cameras = [await Camera.create(
        c, FFMPEG_OUT, MOTION_TIMEOUT
        ) for c in arlo.cameras]

    for c in cameras:
        c.add_picture_callback(callback_picture)

    # Graceful shutdown
    def shutdown(signal, frame):
        logging.info('Shutting down...')
        for c in cameras:
            c.shutdown(signal)
            mqtt_client.loop_stop()
            asyncio.get_running_loop().stop()

    # Register callbacks for shutdown
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    await asyncio.sleep(ARLO_REFRESH)

while True:
    try:
        asyncio.run(main())
        logging.info("Refreshing")
    except RuntimeError:
        logging.info("Closed.")
        break
