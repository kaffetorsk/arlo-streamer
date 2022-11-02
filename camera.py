import subprocess
import logging
import asyncio
import shlex
import os


class Camera(object):
    STATES = ['idle', 'connecting', 'streaming']

    def __init__(self, arlo_camera, ffmpeg_out, motion_timeout):
        self._arlo = arlo_camera
        self.name = self._arlo.name.replace(" ", "_")
        self.ffmpeg_out = shlex.split(ffmpeg_out.format(name=self.name))
        self.timeout = motion_timeout
        self.timeout_task = None
        self._state = None
        self.stream = None
        self.pictures = asyncio.Queue()
        self._listen_pictures = False
        logging.info(f"Camera added: {self.name}")

    async def run(self):
        self.event_loop = asyncio.get_running_loop()
        event_get, event_put = self.make_iter()
        self._arlo.add_attr_callback('*', event_put)
        self.proxy_stream, self.proxy_writer = await self._start_proxy_stream()
        await self.set_state('idle')

        async for device, attr, value in event_get:
            if device == self._arlo:
                await self.on_event(attr, value)

    async def on_event(self, attr, value):
        print(attr, value)
        match attr:
            case 'motionDetected':
                await self.on_motion(value)
            case 'activityState':
                await self.on_arlo_state(value)
            case 'presignedLastImageData':
                await self.pictures.put(value)
            case _:
                pass

    async def on_motion(self, motion):
        logging.info(f"{self.name} motion: {motion}")
        if motion and self.state == 'idle':
            await self.set_state('connecting')

        if (not motion) and self.state != 'idle':
            if self.timeout_task:
                self.timeout_task.cancel()
            self.timeout_task = asyncio.create_task(self._stream_timeout)
            await self.timeout_task

    async def on_arlo_state(self, state):
        if state == 'idle':
            if self.state == 'connecting':
                await self.request_stream()
            if self.state == 'streaming':
                await self.set_state('idle')
        elif state == 'userStreamActive' and self.state != 'streaming':
            await self._stream_started()

    async def set_state(self, new_state):
        if new_state in self.STATES and new_state != self._state:
            self._state = new_state
            logging.info(f"{self.name} state: {new_state}")
            await self._on_state_change(new_state)

    def get_state(self):
        return self._state

    async def _on_state_change(self, new_state):
        match new_state:
            case 'idle':
                await self.stop_stream()
                self.stream = await self._start_idle_stream()
            case 'connecting':
                await self.request_stream()
            case 'streaming':
                pass

    async def _start_proxy_stream(self):
        read, write = os.pipe()
        proc = await asyncio.create_subprocess_exec(
            *(['ffmpeg', '-i', 'pipe:'] + self.ffmpeg_out),
            stdin=read, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return proc, write

    async def _start_idle_stream(self):
        proc = await asyncio.create_subprocess_exec(
            *['ffmpeg', '-re', '-loop', '1', '-f', 'image2',
                '-i', 'arlo.png', '-r', '30', '-c:v', 'libx264',
                '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
            stdout=self.proxy_writer, stderr=subprocess.DEVNULL
            )
        return proc

    async def request_stream(self):
        self.event_loop.run_in_executor(None, self._arlo.get_stream)

    async def _stream_started(self):
        self.state = 'streaming'
        stream = self._arlo.get_stream()
        if stream:
            self.stream.kill()
            self.stream = await asyncio.create_subprocess_exec(
                *['ffmpeg', '-i', stream, '-c:v', 'copy', '-c:a', 'copy',
                    '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
                stdout=self.proxy_writer, stderr=subprocess.DEVNULL
                )
            rc = await self.stream.wait()
        if (not stream) or (rc != -9):
            await self.set_state('connecting')

    async def _stream_timeout(self):
        await asyncio.sleep(self.timeout)
        await self.set_state('idle')

    async def stop_stream(self):
        if self.stream:
            self.stream.kill()
        self.stream = await self._start_idle_stream()
        try:
            await self.event_loop.run_in_executor(
                    None, self._arlo.stop_activity)
        except AttributeError:
            pass

    async def get_pictures(self):
        self._listen_pictures = True
        while True:
            yield self.name, await self.pictures.get()

    async def mqtt_control(self, payload):
        match payload.upper():
            case 'START':
                if self.get_state() == 'idle':
                    await self.set_state('connecting')
            case 'STOP':
                await self.set_state('idle')
            case 'SNAPSHOT':
                await self.event_loop.run_in_executor(
                        None, self._arlo.request_snapshot)

    def make_iter(self):
        queue = asyncio.Queue()

        def put(*args):
            self.event_loop.call_soon_threadsafe(queue.put_nowait, args)

        async def get():
            while True:
                yield await queue.get()
        return get(), put

    def shutdown(self, signal):
        logging.info(f"Shutting down {self.name}")
        for stream in [self.stream, self.proxy_stream]:
            try:
                stream.signal(signal)
            except Exception:
                pass
