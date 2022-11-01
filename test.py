from decouple import config
import pyaarlo
import subprocess
import time

# login with 2FA
arlo = pyaarlo.PyArlo(username=config('ARLO_USER'), password=config('ARLO_PASS'),
                    tfa_source='imap',tfa_type='email',
                    tfa_host=config('IMAP_HOST'),
                    tfa_username=config('IMAP_USER'),
                    tfa_password=config('IMAP_PASS')
                    )

# stream = arlo.cameras[0].get_stream()
# subprocess.run(['ffplay', stream])

def attribute_changed(device, attr, value):
    print('attribute_changed', time.strftime("%H:%M:%S"),
        device.name + ':' + attr + ':' + str(value)[:80]
        )

for camera in arlo.cameras:
    print("camera: name={},device_id={},state={}".format(camera.name,
        camera.device_id, camera.state)
        )

    camera.add_attr_callback('*', attribute_changed)

time.sleep(600)
