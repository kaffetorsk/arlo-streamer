from decouple import config
import pyaarlo
import subprocess
import time

# login with 2FA
arlo = pyaarlo.PyArlo(username=config('ARLO_USER'),
                      password=config('ARLO_PASS'),
                      tfa_source='imap', tfa_type='email',
                      tfa_host=config('IMAP_HOST'),
                      tfa_username=config('IMAP_USER'),
                      tfa_password=config('IMAP_PASS')
                      )


def attribute_changed(device, attr, value):
    print('attribute_changed', time.strftime("%H:%M:%S"),
          device.name + ':' + attr + ':' + str(value)[:80]
          )


for base in arlo.base_stations:
    print("base: name={},device_id={},state={}".format(
        base.name, base.device_id, base.state
        ))
    base.add_attr_callback('*', attribute_changed)


for camera in arlo.cameras:
    print("camera: name={},device_id={},state={}".format(camera.name,
          camera.device_id, camera.state)
          )
    camera.add_attr_callback('*', attribute_changed)

stream = arlo.cameras[1].get_stream()
print(stream)
subprocess.run("ffplay " + stream, shell=True)

time.sleep(600)
