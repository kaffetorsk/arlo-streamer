import subprocess
import logging
import asyncio
import shlex
import os


class Camera(object):
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
        self._arlo = arlo_camera
        self.name = self._arlo.name.replace(" ", "_")
        self.ffmpeg_out = shlex.split(ffmpeg_out.format(name=self.name))
        self.timeout = motion_timeout
        self._timeout_task = None
        self.status_interval = status_interval
        self._state = None
        self._state_event = asyncio.Event()
        self.stream = None
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
        self.event_loop = asyncio.get_running_loop()
        event_get, event_put = self.create_sync_async_channel()
        self._arlo.add_attr_callback('*', event_put)
        self.proxy_stream, self.proxy_writer = await self._start_proxy_stream()
        await self.set_state('idle')
        asyncio.create_task(self._periodic_status_trigger())

        async for device, attr, value in event_get:
            if device == self._arlo:
                asyncio.create_task(self.on_event(attr, value))

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
                self.stream = await self._start_idle_stream()

            case 'streaming':
                await self._start_stream()

    async def _start_proxy_stream(self):
        """
        Start proxy stream. This is the continous video
        stream being sent from ffmpeg. Return process handle
        and write end of pipe.
        """
        read, write = os.pipe()
        proc = await asyncio.create_subprocess_exec(
            *(['ffmpeg', '-i', 'pipe:'] + self.ffmpeg_out),
            stdin=read, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return proc, write

    async def _start_idle_stream(self):
        """
        Start idle picture, writing to the proxy stream and return
        process handle.
        """
        proc = await asyncio.create_subprocess_exec(
            *['ffmpeg', '-re', '-loop', '1', '-f', 'image2',
                '-i', 'eye.png', '-r', '30', '-c:v', 'libx264',
                '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
            stdout=self.proxy_writer, stderr=subprocess.DEVNULL
            )
        return proc

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
                *['ffmpeg', '-i', stream, '-c:v', 'copy', '-c:a', 'copy',
                    '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
                stdout=self.proxy_writer, stderr=subprocess.DEVNULL
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

    async def _periodic_status_trigger(self):
        while True:
            self._state_event.set()
            await asyncio.sleep(self.status_interval)

    async def listen_status(self):
        """
        Async generator, periodically yields status messages for mqtt
        """
        while True:
            await self._state_event.wait()
            status = {
                "battery": self._arlo.battery_level,
                "state": self.get_state()
                }
            yield self.name, status
            self._state_event.clear()

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

    def create_sync_async_channel(self):
        """
        Sync/Async channel

            Returns:
                get(): async generator, yields queued data
                put: function used in sync callbacks
        """
        queue = asyncio.Queue()

        def put(*args):
            self.event_loop.call_soon_threadsafe(queue.put_nowait, args)

        async def get():
            while True:
                yield await queue.get()
                queue.task_done()
        return get(), put

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
                stream.signal(signal)
            except Exception:
                pass
