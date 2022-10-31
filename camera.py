import subprocess
import logging
import asyncio
import shlex
import os

class Camera(object):
    STATES = ['idle', 'connecting', 'streaming']

    @classmethod
    async def create(cls, arlo_camera, event_loop, ffmpeg_out, motion_timeout):
        self = Camera()
        self._arlo = arlo_camera
        self.name = self._arlo.name.replace(" ", "_")
        self.ffmpeg_out = shlex.split(ffmpeg_out.format(name=self.name))
        self.timeout = motion_timeout
        self.event_loop = event_loop
        self._arlo.add_attr_callback('motionDetected', self._motion_detected)
        self._arlo.add_attr_callback('activityState', self._activity_state)
        self._state = 'idle'
        self.proxy_stream, self.proxy_writer = await self._start_proxy_stream()
        self.stream = await self._start_idle_stream()
        self.timeout_task = None
        logging.info(f"Camera added: {self.name}")
        return self


    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        if new_state in self.STATES:
            self._state = new_state
            logging.info(f"{self.name} state: {new_state}")

    def start_stream(self):
        self.state = 'connecting'
        self._arlo.get_stream()

    def _motion_detected(self, device, attr, value):
        logging.info(f"{self.name} motion: {value}")
        if value == True and self.state == 'idle':
            self.start_stream()

        if value == False and self.state != 'idle':
            self._refresh_timeout()

    def _activity_state(self, device, attr, value):
        if  value == 'idle' and self.state == 'connecting':
            self._arlo.get_stream()

        elif value == 'userStreamActive' and self.state != 'streaming':
            asyncio.run_coroutine_threadsafe(self._stream_started(), self.event_loop)

    async def _start_proxy_stream(self):
        read, write = os.pipe()
        proc = await asyncio.create_subprocess_exec(
            #*(['ffmpeg', '-f', 'avi', '-i', 'pipe:'] + self.ffmpeg_out),
            *(['ffmpeg', '-i', 'pipe:'] + self.ffmpeg_out),
            stdin=read, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        return proc, write

    async def _start_idle_stream(self):
        proc = await asyncio.create_subprocess_exec(
            *['ffmpeg', '-re', '-loop', '1', '-f', 'image2', '-i', 'arlo.png',
            '-r', '30', '-c:v', 'libx264', '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
            stdout=self.proxy_writer, stderr=subprocess.DEVNULL
            )
        return proc

    async def _stream_started(self):
        self.state = 'streaming'
        stream = self._arlo.get_stream()
        if stream:
            self.stream.kill()
            self.stream = await asyncio.create_subprocess_exec(
                *['ffmpeg', '-i', stream, '-c:v', 'copy', '-c:a', 'copy', '-bsf', 'dump_extra', '-f', 'mpegts', 'pipe:'],
                stdout=self.proxy_writer, stderr=subprocess.DEVNULL
                )
            rc = await self.stream.wait()
        if (not stream) or (rc != -9):
            self.state = 'connecting'
            self.start_stream()

    def _refresh_timeout(self):
        if self.timeout_task:
            self.timeout_task.cancel()
        self.timeout_task = asyncio.run_coroutine_threadsafe(self._stream_timeout(), self.event_loop)

    async def _stream_timeout(self):
        await asyncio.sleep(self.timeout)
        await self.stop_stream()

    async def stop_stream(self):
        self.stream.kill()
        self.stream = await self._start_idle_stream()
        self.state = 'idle'

    def shutdown(self, signal):
        logging.info(f"Shutting down {self.name}")
        for stream in [self.stream, self.proxy_stream]:
            try:
                stream.signal(signal)
            except Exception:
                pass
