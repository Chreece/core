"""Snapcast media player with native Snapserver stream transport controls."""

from collections.abc import Mapping
import logging
from typing import Any, override

from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.snapcast.coordinator import (
    SnapcastConfigEntry,
    SnapcastUpdateCoordinator,
)
from homeassistant.components.snapcast.entity import SnapcastCoordinatorEntity
from homeassistant.components.snapcast.media_player import (
    SnapcastClientDevice as CoreSnapcastClientDevice,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from snapcast.control.client import Snapclient
from snapcast.control.group import Snapgroup
from snapcast.control.stream import Snapstream

_LOGGER = logging.getLogger(__name__)

_BASE_FEATURES = (
    MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.GROUPING
)

_PLAYBACK_STATUS = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": MediaPlayerState.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SnapcastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Snapcast client entities using the transport-enabled subclass."""
    coordinator = config_entry.runtime_data
    known_client_ids: set[str] = set()

    @callback
    def _update_clients() -> None:
        snapcast_ids = {device.identifier for device in coordinator.server.clients}

        # Keep the HA entity stable while a Snapclient temporarily disappears during
        # a reboot. The inherited entity resolves the current Snapclient object from
        # this immutable identifier when it reconnects.
        ids_to_add = snapcast_ids - known_client_ids
        known_client_ids.update(ids_to_add)

        if not ids_to_add:
            return

        _LOGGER.debug(
            "New snapcast client: %s",
            [
                coordinator.server.client(client_id).friendly_name
                for client_id in ids_to_add
            ],
        )

        async_add_entities(
            [
                SnapcastClientDevice(
                    coordinator, coordinator.server.client(snapcast_id)
                )
                for snapcast_id in ids_to_add
            ]
        )

    _update_clients()
    coordinator.async_add_listener(_update_clients)


class SnapcastClientDevice(CoreSnapcastClientDevice):
    """Snapcast client whose transport commands control its active server stream."""

    def __init__(
        self,
        coordinator: SnapcastUpdateCoordinator,
        device: Snapclient,
    ) -> None:
        """Initialize the Snapcast client."""
        self._client_id = device.identifier
        self._fallback_name = device.friendly_name
        self._bound_device: Snapclient | None = None
        super().__init__(coordinator, device)

    @property
    def _device(self) -> Snapclient | None:
        """Return the current Snapclient object for the immutable client ID."""
        try:
            return self.coordinator.server.client(self._client_id)
        except KeyError:
            return None

    @_device.setter
    def _device(self, device: Snapclient) -> None:
        """Capture identity when the core class assigns its client object."""
        self._client_id = device.identifier
        self._fallback_name = device.friendly_name

    def _require_device(self) -> Snapclient:
        """Return the current client or raise while it is unavailable."""
        if (device := self._device) is None:
            raise HomeAssistantError(
                f"Snapcast client {self._client_id!r} is not currently available"
            )
        return device

    def _bind_device_callback(self) -> None:
        """Move the HA callback to a replacement Snapclient after reconnect."""
        device = self._device
        if device is self._bound_device:
            return

        if self._bound_device is not None:
            self._bound_device.set_callback(None)

        self._bound_device = device
        if device is not None:
            device.set_callback(self.schedule_update_ha_state)

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to the coordinator and current Snapclient object."""
        await super().async_added_to_hass()
        self._bind_device_callback()

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Rebind when python-snapcast replaces a client object on reconnect."""
        self._bind_device_callback()
        super()._handle_coordinator_update()

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Unbind callbacks without dereferencing a disconnected client."""
        if self._bound_device is not None:
            self._bound_device.set_callback(None)
            self._bound_device = None
        await SnapcastCoordinatorEntity.async_will_remove_from_hass(self)

    @property
    @override
    def available(self) -> bool:
        """Return whether this exact Snapcast client currently exists."""
        return super().available and self._device is not None

    @property
    def identifier(self) -> str:
        """Return the immutable Snapcast client identifier."""
        return self._client_id

    @property
    @override
    def name(self) -> str:
        """Return the current client name, retaining a fallback while offline."""
        if (device := self._device) is not None:
            return f"{device.friendly_name} Snapcast Client"
        return f"{self._fallback_name} Snapcast Client"

    @property
    def latency(self) -> float | None:
        """Return current client latency."""
        if (device := self._device) is None:
            return None
        return device.latency

    @property
    @override
    def is_volume_muted(self) -> bool:
        """Return current mute state."""
        if (device := self._device) is None:
            return False
        return device.muted

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute exactly this immutable Snapcast client."""
        await self._require_device().set_muted(mute)
        self.async_write_ha_state()

    @property
    @override
    def volume_level(self) -> float | None:
        """Return current client volume."""
        if (device := self._device) is None:
            return None
        return device.volume / 100

    @override
    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume on exactly this immutable Snapcast client."""
        await self._require_device().set_volume(round(volume * 100))
        self.async_write_ha_state()

    async def async_snapshot(self) -> None:
        """Snapshot this exact client's state."""
        self._require_device().snapshot()

    async def async_restore(self) -> None:
        """Restore this exact client's state."""
        await self._require_device().restore()
        self.async_write_ha_state()

    async def async_set_latency(self, latency) -> None:
        """Set latency on exactly this immutable Snapcast client."""
        await self._require_device().set_latency(latency)
        self.async_write_ha_state()

    @property
    def _current_group(self) -> Snapgroup | None:
        """Return the group the client is associated with."""
        if (device := self._device) is None:
            return None
        return device.group

    @property
    def _current_stream(self) -> Snapstream | None:
        """Return the active Snapserver stream."""
        if self._current_group is None:
            return None
        try:
            return self.coordinator.server.stream(self._current_group.stream)
        except KeyError:
            return None

    @property
    def _stream_properties(self) -> Mapping[str, Any]:
        """Return properties exposed by the active stream control plugin."""
        if (stream := self._current_stream) is None or not stream.properties:
            return {}
        return stream.properties

    @property
    @override
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Expose transport features supported by the active Snapserver stream."""
        features = _BASE_FEATURES
        properties = self._stream_properties

        if not properties.get("canControl", False):
            return features

        if properties.get("canPlay", False):
            features |= MediaPlayerEntityFeature.PLAY
        if properties.get("canPause", False):
            features |= MediaPlayerEntityFeature.PAUSE
        if properties.get("canGoNext", False):
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if properties.get("canGoPrevious", False):
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if properties.get("canSeek", False):
            features |= MediaPlayerEntityFeature.SEEK

        features |= MediaPlayerEntityFeature.STOP
        return features

    @property
    @override
    def state(self) -> MediaPlayerState | None:
        """Return stream playback state when the control plugin provides it."""
        if (device := self._device) is None or not device.connected:
            return MediaPlayerState.OFF

        if (
            self.is_volume_muted
            or self._current_group is None
            or self._current_group.muted
        ):
            return MediaPlayerState.IDLE

        playback_status = self._stream_properties.get("playbackStatus")
        if playback_status in _PLAYBACK_STATUS:
            return _PLAYBACK_STATUS[playback_status]

        return super().state

    async def _async_stream_control(
        self, command: str, params: dict[str, Any] | None = None
    ) -> None:
        """Send a native Stream.Control command to the active Snapserver stream."""
        if self._current_group is None:
            raise HomeAssistantError(
                f"{self.entity_id} has no Snapcast group and no active stream to control"
            )

        stream_id = self._current_group.stream
        result = await self.coordinator.server.stream_control(
            stream_id, command, params or {}
        )

        if isinstance(result, dict) and "code" in result:
            raise HomeAssistantError(
                f"Snapserver rejected {command!r} for stream {stream_id!r}: "
                f"{result.get('message', result)}"
            )

    @override
    async def async_media_play(self) -> None:
        """Start playback through the active Snapserver stream."""
        await self._async_stream_control("play")

    @override
    async def async_media_pause(self) -> None:
        """Pause playback through the active Snapserver stream."""
        await self._async_stream_control("pause")

    @override
    async def async_media_play_pause(self) -> None:
        """Toggle playback through the active Snapserver stream."""
        await self._async_stream_control("playPause")

    @override
    async def async_media_stop(self) -> None:
        """Stop playback through the active Snapserver stream."""
        await self._async_stream_control("stop")

    @override
    async def async_media_next_track(self) -> None:
        """Skip to the next track through the active Snapserver stream."""
        await self._async_stream_control("next")

    @override
    async def async_media_previous_track(self) -> None:
        """Skip to the previous track through the active Snapserver stream."""
        await self._async_stream_control("previous")

    @override
    async def async_media_seek(self, position: float) -> None:
        """Seek to an absolute position through the active Snapserver stream."""
        await self._async_stream_control(
            "setPosition", {"position": float(position)}
        )
