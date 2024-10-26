# Example: Frigate
This simple example shows how you could setup arlo-streamer for frigate.

## Prerequisites and assumptions
- Arlo account set up with email as 2FA. Email account must support IMAP (e.g. outlook.com)
- (optional) MQTT Broker running on the same host. If you're not using MQTT, remove the relevant lines in `docker-compose.yml` and `.streamer-env`.
- Frigate running on the same host.
- Frigate and MQTT not part of the same compose as *arlo-streamer*

## Setup
1. Clone this folder
2. Edit `.streamer-env` with your details
3. Run `docker compose up -d`
4. Edit frigate docker compose:
```
services:
    frigate:
        ...
        extra_hosts:
            - "host.docker.internal:host-gateway"
```
5. Add cameras to frigate.
The cameras will be availaible at: `rtmp://host.docker.internal:1935/live/camera_name`. *camera_name* is the name you set for the camera in the arlo app, with some formating added. Check the log from this container for the exact name.

Example frigate config:
```
cameras:
  camera_name:
    ffmpeg:
      inputs:
        - path: rtmp://host.docker.internal:1935/live/camera_name
          input_args: -avoid_negative_ts make_zero -flags low_delay -strict experimental -fflags +genpts+discardcorrupt -rw_timeout 30000000 -f live_flv
          roles:
            - detect
            - record
    detect:
      width: 1280
      height: 768
```
Notice the input args, some tuning might be needed. This atleast works in my setup.

Good luck!