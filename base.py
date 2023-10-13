import logging
import json
from device import Device


class Base(Device):
    """
    Attributes
    ----------
    name : str
        internal name of the base (not necessarily identical to arlo)
    status_interval: int
        interval of status messages from generator (seconds)
    """

    def __init__(self, arlo_base, status_interval):
        super().__init__(arlo_base, status_interval)
        logging.info(f"Base added: {self.name}")

    # Distributes events to correct handler
    async def on_event(self, attr, value):
        match attr:
            case 'activeMode':
                self._state_event.set()
                logging.info(f"{self.name} mode: {value}")
            case _:
                pass

    def get_status(self):
        return {
            "mode": self._arlo.mode,
            "siren": self._arlo.siren_state
            }

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
            logging.warning(f"{self.name}: Invalid data for MQTT control")

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
            logging.warning(f"{self.name}: Invalid mode, ignored")

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
                    logging.warning(f"{self.name}: Invalid siren arguments")
            case _:
                pass
