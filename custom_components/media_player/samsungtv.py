"""
Support for interface with an Samsung TV.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/media_player.samsungtv/
"""
import logging
import socket

import voluptuous as vol

from homeassistant.components.media_player import (
    SUPPORT_NEXT_TRACK, SUPPORT_PAUSE, SUPPORT_PREVIOUS_TRACK,
    SUPPORT_TURN_ON, SUPPORT_TURN_OFF, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_STEP,
    SUPPORT_PLAY, MediaPlayerDevice, PLATFORM_SCHEMA)
from homeassistant.const import (
    CONF_HOST, CONF_NAME, STATE_OFF, STATE_ON, STATE_UNKNOWN, CONF_PORT, CONF_MAC)
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['samsungctl==0.6.0',
                'wakeonlan==0.2.2']

_LOGGER = logging.getLogger(__name__)

CONF_TIMEOUT = 'timeout'

DEFAULT_NAME = 'Samsung TV Remote'
DEFAULT_PORT = 55000
DEFAULT_TIMEOUT = 0

KNOWN_DEVICES_KEY = 'samsungtv_known_devices'

SUPPORT_SAMSUNGTV = SUPPORT_PAUSE | SUPPORT_VOLUME_STEP | \
    SUPPORT_VOLUME_MUTE | SUPPORT_PREVIOUS_TRACK | \
    SUPPORT_NEXT_TRACK | SUPPORT_TURN_OFF | SUPPORT_PLAY

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_MAC): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Samsung TV platform."""
    known_devices = hass.data.get(KNOWN_DEVICES_KEY)
    if known_devices is None:
        known_devices = set()
        hass.data[KNOWN_DEVICES_KEY] = known_devices

    # Is this a manual configuration?
    if config.get(CONF_HOST) is not None:
        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)
        name = config.get(CONF_NAME)
        mac = config.get(CONF_MAC)
        timeout = config.get(CONF_TIMEOUT)
    elif discovery_info is not None:
        tv_name, model, host = discovery_info
        name = "{} ({})".format(tv_name, model)
        port = DEFAULT_PORT
        timeout = DEFAULT_TIMEOUT
    else:
        _LOGGER.warning(
            'Internal error on samsungtv component. Cannot determine device')
        return

    # Only add a device once, so discovered devices do not override manual
    # config.
    ip_addr = socket.gethostbyname(host)
    if ip_addr not in known_devices:
        known_devices.add(ip_addr)
        add_devices([SamsungTVDevice(host, port, name, mac, timeout)])
        _LOGGER.info("Samsung TV %s:%d added as '%s'", host, port, name)
    else:
        _LOGGER.info("Ignoring duplicate Samsung TV %s:%d", host, port)


class SamsungTVDevice(MediaPlayerDevice):
    """Representation of a Samsung TV."""

    def __init__(self, host, port, name, mac, timeout):
        """Initialize the Samsung device."""
        from samsungctl import exceptions
        from samsungctl import Remote
        from wakeonlan import wol
            
        # Save a reference to the imported classes
        self._exceptions_class = exceptions
        self._remote_class = Remote
        self._name = name
        self._wol = wol
        self._mac = mac
        
        # Assume that the TV is not muted
        self._muted = False
        # Assume that the TV is in Play mode
        self._playing = True
        self._state = STATE_UNKNOWN
        self._remote = None
        # Generate a configuration for the Samsung library
        self._config = {
            'name': 'HomeAssistant',
            'description': name,
            'id': 'ha.component.samsung',
            'port': port,
            'host': host,
            'timeout': timeout,
        }

        if self._config['port'] == 8001:
            self._config['method'] = 'websocket'
        else:
            self._config['method'] = 'legacy'

    def update(self):
        """Retrieve the latest data."""
        # Send an empty key to see if we are still connected
        return self.send_key('KEY')

    def get_remote(self):
        """Create or return a remote control instance."""
        if self._remote is None:
            # We need to create a new instance to reconnect.
            self._remote = self._remote_class(self._config)

        return self._remote

    def send_key(self, key):
        """Send a key to the tv and handles exceptions."""
        try:
            self.get_remote().control(key)
            if key == 'KEY_POWER' or key == 'KEY_POWEROFF':
                # Force closing of remote session to provide instant UI feedback
                self.get_remote().close()
                self._state = STATE_OFF
            else:
                self._state = STATE_ON
        except (self._exceptions_class.UnhandledResponse,
                self._exceptions_class.AccessDenied, BrokenPipeError):
            # We got a response so it's on.
            # BrokenPipe can occur when the commands is sent to fast
            self._state = STATE_ON
            self._remote = None
            return False
        except (self._exceptions_class.ConnectionClosed, OSError):
            self._state = STATE_OFF
            self._remote = None
            return False


        
        return True

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def supported_features(self):
        """Flag of media commands that are supported."""
        if self._mac:
          return SUPPORT_SAMSUNGTV | SUPPORT_TURN_ON
        return SUPPORT_SAMSUNGTV

    def turn_on(self):
        """Turn on the media player."""
        if self._mac:
            self._wol.send_magic_packet(self._mac)
        self.update()
        
    def turn_off(self):
        """Turn off media player."""
        self.update()
        if self._config['method'] == 'websocket':
            self.send_key('KEY_POWER')
        else:
            self.send_key('KEY_POWEROFF')

    def volume_up(self):
        """Volume up the media player."""
        self.send_key('KEY_VOLUP')

    def volume_down(self):
        """Volume down media player."""
        self.send_key('KEY_VOLDOWN')

    def mute_volume(self, mute):
        """Send mute command."""
        self.send_key('KEY_MUTE')
        self.update()        

    def media_play_pause(self):
        """Simulate play pause media player."""
        if self._playing:
            self.media_pause()
        else:
            self.media_play()
        self.update()            

    def media_play(self):
        """Send play command."""
        self._playing = True
        self.send_key('KEY_PLAY')
        self.update()        

    def media_pause(self):
        """Send media pause command to media player."""
        self._playing = False
        self.send_key('KEY_PAUSE')
        self.update()

    def media_next_track(self):
        """Send next track command."""
        self.send_key('KEY_FF')
        self.update()        

    def media_previous_track(self):
        """Send the previous track command."""
        self.send_key('KEY_REWIND')
        self.update()        

    # def turn_on(self):
        # """Turn the media player on."""
        # self.send_key('KEY_POWERON')