from decouple import config
import pyaarlo
import time
import asyncio
import logging
import signal
from camera import Camera

logging.basicConfig(
    level = logging.INFO,
    format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

# def attribute_changed(device, attr, value):
#     print('attribute_changed', time.strftime("%H:%M:%S"), device.name + ':' + attr + ':' + str(value)[:80])

async def main():
    # login with 2FA
    arlo = pyaarlo.PyArlo(username=config('ARLO_USER'), password=config('ARLO_PASS'),
                        tfa_source='imap',tfa_type='email',
                        tfa_host=config('IMAP_HOST'),
                        tfa_username=config('IMAP_USER'),
                        tfa_password=config('IMAP_PASS')
                        )

    # for camera in arlo.cameras:
    #     print("camera: name={},device_id={},state={}".format(camera.name,camera.device_id,camera.state))
    #     camera.add_attr_callback('*', attribute_changed)

    cameras = [await Camera.create(
        c, asyncio.get_running_loop(), config('FFMPEG_OUT'), int(config('MOTION_TIMEOUT'))
        ) for c in arlo.cameras]

    # Graceful shutdown
    def shutdown(signal, frame):
        logging.info('Shutting down...')
        for c in cameras:
            c.shutdown(signal)
            asyncio.get_running_loop().stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # tasks = None
    # while True:
    #     if tasks != asyncio.all_tasks():
    #         print(asyncio.current_task())
    #         print("===============")
    #         tasks = asyncio.all_tasks()
    #         for t in tasks:
    #             print(t)
    #     await asyncio.sleep(1)
    await asyncio.sleep(int(config('ARLO_REFRESH')))

while True:
    try:
        asyncio.run(main())
        logging.info("Refreshing")
    except RuntimeError:
        logging.info("Closed.")
        break
