from decouple import config
import pyaarlo
import asyncio
import logging
import signal
from camera import Camera
import mqtt

ARLO_USER = config('ARLO_USER')
ARLO_PASS = config('ARLO_PASS')
IMAP_HOST = config('IMAP_HOST')
IMAP_USER = config('IMAP_USER')
IMAP_PASS = config('IMAP_PASS')
MQTT_BROKER = config('MQTT_BROKER', default=None)
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
    [asyncio.create_task(c.run()) for c in cameras]
    if MQTT_BROKER:
        asyncio.create_task(mqtt.mqtt_client(cameras))

    # Graceful shutdown
    def shutdown(signal, frame):
        logging.info('Shutting down...')
        for c in cameras:
            c.shutdown(signal)
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
