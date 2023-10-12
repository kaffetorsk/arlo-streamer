import logging
import asyncio
import json


class Base(object):
    """
    Attributes
    ----------
    name : str
        internal name of the base (not necessarily identical to arlo)
    status_interval: int
        interval of status messages from generator (seconds)
    """

    def __init__(self, arlo_base, status_interval):
        self._arlo = arlo_base
        self.name = self._arlo.name.replace(" ", "_").lower()
        self.status_interval = status_interval
        self._state_event = asyncio.Event()
        logging.info(f"Base added: {self.name}")

    async def run(self):
        """
        Initializes the Base.
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
        match attr:
            case 'activeMode':
                await self._periodic_status_trigger()
            case _:
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
            status = {
                "mode": self._arlo.mode,
                "siren": self._arlo.siren_state
                }
            yield self.name, status
            self._state_event.clear()

    async def mqtt_control(self, payload):
        """
        Handles incoming MQTT commands
        """
        handlers = {
            'mode': self.set_mode,
            'siren': self.set_siren
        }

        try:
            payload = json.loads(payload)
            for k, v in payload.items():
                if k in handlers:
                    self.event_loop.run_in_executor(None, handlers[k], v)
        except Exception:
            logging.warning("Invalid data for MQTT control")

    def set_mode(self, mode):
        """"
        Sets mode of Base Station
        """
        try:
            mode = mode.lower()
            if mode not in self._arlo.available_modes:
                raise ValueError
            self._arlo.mode = mode
        except (AttributeError, ValueError):
            logging.warning("Invalid mode")

    def set_siren(self, state):
        """
        Sets siren (on/off/on with specified duration and volume)
        """
        match state:
            case 'on':
                self._arlo.siren_on()
            case 'off':
                self._arlo.siren_off()
            case dict():
                try:
                    self._arlo.siren_on(**state)
                except AttributeError:
                    logging.warning("Invalid siren arguments")
            case _:
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
