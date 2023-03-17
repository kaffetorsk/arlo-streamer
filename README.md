[![Dependency Review](https://github.com/kaffetorsk/arlo-streamer/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/kaffetorsk/arlo-streamer/actions/workflows/dependency-review.yml) [![CodeQL](https://github.com/kaffetorsk/arlo-streamer/actions/workflows/codeql.yml/badge.svg)](https://github.com/kaffetorsk/arlo-streamer/actions/workflows/codeql.yml)

# arlo-streamer
Python script that turns arlo cameras into continuous streams through ffmpeg
This allow arlo cameras to be used in the NVR of your choosing. (e.g. [Frigate](https://frigate.video/))

The streams will provide an "idle" picture when the camera is not actively streaming.
Motion will trigger an active stream, replacing the "idle" picture with the actual camera stream.

## Usage
Config through environment variables, if `.env` is present it will be checked for variables.
Where applicable `{name}` will be replaced by camera name.
### Required
```
ARLO_USER: Arlo account name
ARLO_PASS: Arlo password
IMAP_HOST: imap server to use for 2FA (see [pyaarlo](https://github.com/twrecked/pyaarlo) for details)
IMAP_USER: imap account
IMAP_PASS: imap password
FFMPEG_OUT: out-string for ffmpeg. (e.g. -c:v copy -c:a copy -f flv rtmp://127.0.0.1:1935/live/{name})
```
### Optional
```
ARLO_REFRESH: How often to refresh login (in seconds) (default: 3600)
MOTION_TIMEOUT: How long to provide active stream after motion (in seconds) (default: 60)
MQTT_BROKER: If specified, will be used to publish snapshots and status, and control the camera (see MQTT).
MQTT_TOPIC_PICTURE: snapshots will be published to this topic. (default: arlo/picture)
MQTT_TOPIC_STATUS: status will be published to this topic. (default: arlo/status/{name})
MQTT_TOPIC_CONTROL: control will be read on this topic. (default: arlo/control/{name})
MQTT_TOPIC_MOTION: motion events will be published to this topic. (default: arlo/motion/{name})
MQTT_RECONNECT_INTERVAL: Wait this amount before retrying connection to broker (in seconds) (default: 5)
STATUS_INTERVAL: Time between published status messages (in seconds) (default: 120)
DEBUG: True enables full debug (default: False)
```
### Running
```
python main.py
```
or
```
docker run -d --env-file .env kaffetorsk/arlo-streamer
```
### MQTT
#### Pictures
JSON with "payload" set to base64 encoded image. "filename" set to "timestamp camera_name.jpg"
#### Status
JSON
#### Motion
Boolean
#### Control
Payload in a simple string.
```
"START" and "STOP": Starts and stops active stream
"SNAPSHOT": Requests snapshot to be taken
```
## Notes
This repo is in early development, treat it as such and feel free to submit PRs.
