"""Snapcast media player with native Snapserver stream transport controls."""

from collections.abc import Mapping
import logging
from typing import Any, override

from snapcast.control.client import Snapclient
from snapcast.control.group import Snapgroup
from snapcast.control.stream import Snapstream

from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.snapcast.const import CLIENT_PREFIX, DOMAIN
from homeassistant.components.snapcast.coordinator import (
    SnapcastConfigEntry,
    SnapcastUpdateCoordinator,
)
from homeassistant.components.snapcast.media_player import (
    SnapcastClientDevice as CoreSnapcastClientDevice,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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

        ids_to_add = snapcast_ids - known_client_ids
        ids_to_remove = known_client_ids - snapcast_ids

        known_client_ids.difference_update(ids_to_remove)
        known_client_ids.update(ids_to_add)

        if not (ids_to_add | ids_to_remove):
            return

        _LOGGER.debug(
            "New snapcast client: %s",
            [coordinator.server.client(client_id).friendly_name for client_id in ids_to_add],
        )
        _LOGGER.debug("Remove snapcast client IDs: %s", list(ids_to_remove))

        async_add_entities(
            [
                SnapcastClientDevice(
                    coordinator, coordinator.server.client(snapcast_id)
                )
                for snapcast_id in ids_to_add
            ]
        )

        entity_registry = er.async_get(hass)
        for snapcast_id in ids_to_remove:
            if entity_id := entity_registry.async_get_entity_id(
                MEDIA_PLAYER_DOMAIN,
                DOMAIN,
                SnapcastClientDevice.get_unique_id(coordinator.host_id, snapcast_id),
            ):
                entity_registry.async_remove(entity_id)

    _update_clients()
    coordinator.async_add_listener(_update_clients)


class SnapcastClientDevice(CoreSnapcastClientDevice):
    """Snapcast client whose transport commands control its active server stream."""

    _device: Snapclient

    def __init__(
        self,
        coordinator: SnapcastUpdateCoordinator,
        device: Snapclient,
    ) -> None:
        """Initialize the Snapcast client."""
        super().__init__(coordinator, device)

    @property
    def _current_group(self) -> Snapgroup | None:
        """Return the group the client is associated with."""
        return self._device.group

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

        features |= MediaPlayerEntityFeature.STOP
        return features

    @property
    @override
    def state(self) -> MediaPlayerState | None:
        """Return stream playback state when the control plugin provides it."""
        if not self._device.connected:
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

    async def _async_stream_control(self, command: str) -> None:
        """Send a native Stream.Control command to the active Snapserver stream."""
        if self._current_group is None:
            raise HomeAssistantError(
                f"{self.entity_id} has no Snapcast group and no active stream to control"
            )

        stream_id = self._current_group.stream
        result = await self.coordinator.server.stream_control(stream_id, command, {})

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
