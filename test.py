from decouple import config
import pyaarlo
import subprocess

# login with 2FA
arlo = pyaarlo.PyArlo(username=config('ARLO_USER'), password=config('ARLO_PASS'),
                    tfa_source='imap',tfa_type='email',
                    tfa_host=config('IMAP_HOST'),
                    tfa_username=config('IMAP_USER'),
                    tfa_password=config('IMAP_PASS')
                    )

stream = arlo.cameras[0].get_stream()

subprocess.run(['ffplay', stream])
