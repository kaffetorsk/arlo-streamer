import asyncio


class Device(object):
    """
    Attributes
    ----------
    name : str
        internal name of the device (not necessarily identical to arlo)
    status_interval: int
        interval of status messages from generator (seconds)
    """

    def __init__(self, arlo_device, status_interval):
        self._arlo = arlo_device
        self.name = self._arlo.name.replace(" ", "_").lower()
        self.status_interval = status_interval
        self._state_event = asyncio.Event()

    async def run(self):
        """
        Initializes the Device.
        Creates event channel between pyaarlo callbacks and async generator.
        Listens for and passes events to handler.
        """
        self.event_loop = asyncio.get_running_loop()
        event_get, event_put = self.create_sync_async_channel()
        self._arlo.add_attr_callback('*', event_put)
        asyncio.create_task(self._periodic_status_trigger())

        async for device, attr, value in event_get:
            if device == self._arlo:
                asyncio.create_task(self.on_event(attr, value))

    # Distributes events to correct handler
    async def on_event(self, attr, value):
        pass

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
            status = self.get_status()
            yield self.name, status
            self._state_event.clear()

    def get_status(self):
        pass

    async def mqtt_control(self, payload):
        pass

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
