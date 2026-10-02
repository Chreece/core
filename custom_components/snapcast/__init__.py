"""Snapcast custom test integration with native stream transport controls."""

from homeassistant.components.snapcast import (
    async_setup as _core_async_setup,
    async_setup_entry as _core_async_setup_entry,
    async_unload_entry as _core_async_unload_entry,
)
from homeassistant.components.snapcast.coordinator import SnapcastConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Snapcast using Home Assistant's built-in implementation."""
    return await _core_async_setup(hass, config)


async def async_setup_entry(hass: HomeAssistant, entry: SnapcastConfigEntry) -> bool:
    """Set up Snapcast from a config entry."""
    return await _core_async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: SnapcastConfigEntry) -> bool:
    """Unload a Snapcast config entry."""
    return await _core_async_unload_entry(hass, entry)
