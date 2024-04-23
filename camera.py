import subprocess
import logging
import asyncio
import shlex
import os
from device import Device
from decouple import config

DEBUG = config('DEBUG', default=False, cast=bool)


class Camera(Device):
    """
    Attributes
    ----------
    name : str
        internal name of the camera (not necessarily identical to arlo)
    ffmpeg_out : str
        ffmpeg output string
    timeout: int
        motion timeout of live stream (seconds)
    status_interval: int
        interval of status messages from generator (seconds)
    stream: asyncio.subprocess.Process
        current ffmpeg stream (idle or active)
    """

    # Possible states
    STATES = ['idle', 'streaming']

    def __init__(self, arlo_camera, ffmpeg_out,
                 motion_timeout, status_interval):
        super().__init__(arlo_camera, status_interval)
        self.ffmpeg_out = shlex.split(ffmpeg_out.format(name=self.name))
        self.timeout = motion_timeout
        self._timeout_task = None
        self.motion = False
        self._state = None
        self._motion_event = asyncio.Event()
        self.stream = None
        self.proxy_stream = None
        self.proxy_reader, self.proxy_writer = os.pipe()
        self._pictures = asyncio.Queue()
        self._listen_pictures = False
        logging.info(f"Camera added: {self.name}")

    async def run(self):
        """
        Starts the camera, waits indefinitely for camera to become available.
        Creates event channel between pyaarlo callbacks and async generator.
        Listens for and passes events to handler.
        """
        while self._arlo.is_unavailable:
            await asyncio.sleep(5)
        await self.set_state('idle')
        asyncio.create_task(self._start_proxy_stream())
        await super().run()

    # Distributes events to correct handler
    async def on_event(self, attr, value):
        match attr:
            case 'motionDetected':
                await self.on_motion(value)
            case 'activityState':
                await self.on_arlo_state(value)
            case 'presignedLastImageData':
                if self._listen_pictures:
                    self.put_picture(value)
            case _:
                pass

    # Activates stream on motion
    async def on_motion(self, motion):
        """
        Handles motion events. Either starts live stream or resets
        live stream timeout.
        """
        self.motion = motion
        self._motion_event.set()
        logging.info(f"{self.name} motion: {motion}")
        if motion:
            await self.set_state('streaming')

        else:
            if self._timeout_task:
                self._timeout_task.cancel()
            if not motion:
                self._timeout_task = asyncio.create_task(
                    self._stream_timeout()
                    )

    async def on_arlo_state(self, state):
        """
        Handles pyaarlo state change, either requests stream or handles
        running stream.
        """
        if state == 'idle':
            if self.get_state() == 'streaming':
                await self._start_stream()
        elif state == 'userStreamActive' and self.get_state() != 'streaming':
            await self.set_state('streaming')

    # Set state in accordance to STATES
    async def set_state(self, new_state):
        if new_state in self.STATES and new_state != self._state:
            self._state = new_state
            logging.info(f"{self.name} state: {new_state}")
            await self._on_state_change(new_state)

    def get_state(self):
        return self._state

    # Handle internal state change, stop or start stream
    async def _on_state_change(self, new_state):
        self._state_event.set()
        match new_state:
            case 'idle':
                self.stop_stream()
                asyncio.create_task(self._start_idle_stream())

            case 'streaming':
                await self._start_stream()

    async def _start_proxy_stream(self):
        """
        Start proxy stream. This is the continous video
        stream being sent from ffmpeg.
        """
        exit_code = 1
        while exit_code > 0:
            self.proxy_stream = await asyncio.create_subprocess_exec(
                *(['ffmpeg', '-i', 'pipe:'] + self.ffmpeg_out),
                stdin=self.proxy_reader,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE if DEBUG else subprocess.DEVNULL
                )

            if DEBUG:
                asyncio.create_task(
                    self._log_stderr(self.proxy_stream, 'proxy_stream')
                    )

            exit_code = await self.proxy_stream.wait()

            if exit_code > 0:
                logging.warning(
                    f"Proxy stream for {self.name} exited unexpectedly "
                    f"with code {exit_code}. Restarting..."
                    )
                await asyncio.sleep(3)

    async def _start_idle_stream(self):
        """
        Start idle picture, writing to the proxy stream
        """
        exit_code = 1
        while exit_code > 0:
            self.stream = await asyncio.create_subprocess_exec(
                *['ffmpeg', '-re', '-stream_loop', '-1', '-i', 'idle.mp4',
                  '-c:v', 'copy',
                  '-c:a', 'libmp3lame', '-ar', '44100', '-b:a', '8k',
                  '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
                stdin=subprocess.DEVNULL,
                stdout=self.proxy_writer,
                stderr=subprocess.PIPE if DEBUG else subprocess.DEVNULL
                )

            if DEBUG:
                asyncio.create_task(
                    self._log_stderr(self.stream, 'idle_stream')
                    )

            exit_code = await self.stream.wait()

            if exit_code > 0:
                logging.warning(
                    f"Idle stream for {self.name} exited unexpectedly "
                    f"with code {exit_code}. Restarting..."
                    )
                await asyncio.sleep(3)

    async def _start_stream(self):
        """
        Request stream, grab it, kill idle stream and start new ffmpeg instance
        writing to proxy.
        """
        stream = await self.event_loop.run_in_executor(None,
                                                       self._arlo.get_stream)
        if stream:
            self.stop_stream()

            self.stream = await asyncio.create_subprocess_exec(
                *['ffmpeg', '-i', stream, '-c:v', 'copy',
                  '-c:a', 'libmp3lame', '-ar', '44100',
                  '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
                stdin=subprocess.DEVNULL,
                stdout=self.proxy_writer,
                stderr=subprocess.PIPE if DEBUG else subprocess.DEVNULL
                )

            if DEBUG:
                asyncio.create_task(
                    self._log_stderr(self.stream, 'live_stream')
                    )

    async def _stream_timeout(self):
        await asyncio.sleep(self.timeout)
        await self.set_state('idle')

    def stop_stream(self):
        """
        Stop live or idle stream (not proxy stream)
        """
        if self.stream:
            try:
                self.stream.kill()
            except ProcessLookupError:
                pass

    async def get_pictures(self):
        """
        Async generator, yields snapshots from pyaarlo
        """
        self._listen_pictures = True
        while True:
            yield self.name, await self._pictures.get()
            self._pictures.task_done()

    def put_picture(self, pic):
        """
        Put picture into the queue
        """
        try:
            self._pictures.put_nowait(pic)
        except asyncio.QueueFull:
            logging.info("picture queue full, ignoring")

    def get_status(self):
        return {
            "battery": self._arlo.battery_level,
            "state": self.get_state()
            }

    async def listen_motion(self):
        """
        Async generator, yields motion state on change
        """
        while True:
            await self._motion_event.wait()
            yield self.name, self.motion
            self._motion_event.clear()

    async def mqtt_control(self, payload):
        """
        Handles incoming MQTT commands
        """
        match payload.upper():
            case 'START':
                await self.set_state('streaming')
            case 'STOP':
                await self.set_state('idle')
            case 'SNAPSHOT':
                await self.event_loop.run_in_executor(
                        None, self._arlo.request_snapshot)

    async def _log_stderr(self, stream, label):
        """
        Continuously read from stderr and log the output.
        """
        while True:
            try:
                line = await stream.stderr.readline()
                if line:
                    logging.debug(
                        f"{self.name} - {label}: {line.decode().strip()}"
                        )
                else:
                    break
            except ValueError:
                pass

    async def shutdown_when_idle(self):
        """
        Shutdown camera, wait for idle
        """
        if self.get_state() != 'idle':
            logging.info(f"{self.name} active, waiting...")
            while self.get_state() != 'idle':
                await asyncio.sleep(1)
        self.shutdown(None)

    def shutdown(self, signal):
        """
        Immediate shutdown
        """
        logging.info(f"Shutting down {self.name}")
        for stream in [self.stream, self.proxy_stream]:
            try:
                stream.terminate()
            except Exception:
                pass
