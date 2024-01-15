from decouple import config
import pyaarlo
import asyncio
import logging
import signal
from camera import Camera
from base import Base

# Read config from ENV
ARLO_USER = config('ARLO_USER')
ARLO_PASS = config('ARLO_PASS')
IMAP_HOST = config('IMAP_HOST')
IMAP_USER = config('IMAP_USER')
IMAP_PASS = config('IMAP_PASS')
MQTT_BROKER = config('MQTT_BROKER', default=None)
FFMPEG_OUT = config('FFMPEG_OUT')
MOTION_TIMEOUT = config('MOTION_TIMEOUT', default=60, cast=int)
STATUS_INTERVAL = config('STATUS_INTERVAL', default=120, cast=int)
DEBUG = config('DEBUG', default=False, cast=bool)
PYAARLO_BACKEND = config('PYAARLO_BACKEND', default=None)
PYAARLO_REFRESH_DEVICES = config('PYAARLO_REFRESH_DEVICES', default=0, cast=int)
PYAARLO_STREAM_TIMEOUT = config('PYAARLO_STREAM_TIMEOUT', default=0, cast=int)
PYAARLO_STORAGE_DIR = config('PYAARLO_STORAGE_DIR', default=None)

# Initialize logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

shutdown_event = asyncio.Event()


async def main():
    # login to arlo with 2FA
    arlo_args = {
        'username': ARLO_USER,
        'password': ARLO_PASS,
        'tfa_source': 'imap',
        'tfa_type': 'email',
        'tfa_host': IMAP_HOST,
        'tfa_username': IMAP_USER,
        'tfa_password': IMAP_PASS
    }

    if PYAARLO_REFRESH_DEVICES:
        arlo_args['refresh_devices_every'] = PYAARLO_REFRESH_DEVICES

    if PYAARLO_STREAM_TIMEOUT:
        arlo_args['stream_timeout'] = PYAARLO_STREAM_TIMEOUT

    if PYAARLO_BACKEND:
        arlo_args['backend'] = PYAARLO_BACKEND

    if PYAARLO_STORAGE_DIR:
        arlo_args['storage_dir'] = PYAARLO_STORAGE_DIR

    arlo = pyaarlo.PyArlo(**arlo_args)

    # Initialize bases
    bases = [Base(b, STATUS_INTERVAL) for b in arlo.base_stations]

    # Initialize cameras
    cameras = [Camera(
        c, FFMPEG_OUT, MOTION_TIMEOUT, STATUS_INTERVAL
        ) for c in arlo.cameras]

    # Start both
    [asyncio.create_task(d.run()) for d in cameras + bases]

    # Initialize mqtt service
    if MQTT_BROKER:
        import mqtt
        asyncio.create_task(mqtt.mqtt_client(cameras, bases))

    # Graceful shutdown
    def request_shutdown(signal, frame):
        logging.info('Shutdown requested...')
        shutdown_event.set()

    # Register callbacks for shutdown
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    # Wait for shutdown
    await shutdown_event.wait()

    logging.info('Shutting down...')
    for c in cameras:
        c.shutdown(signal)

    arlo.stop(logout=True)

# Run main
try:
    asyncio.run(main())
except RuntimeError:
    logging.info("Closed.")
