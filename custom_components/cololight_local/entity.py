"""Base entity of the Cololight (local) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL_NAMES
from .coordinator import CololightCoordinator


class CololightEntity(CoordinatorEntity[CololightCoordinator]):
    """An entity of one lamp, named after its device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CololightCoordinator, key: str | None = None) -> None:
        super().__init__(coordinator)
        mac = coordinator.mac
        self._attr_unique_id = mac if key is None else f"{mac}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={(CONNECTION_NETWORK_MAC, mac)},
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES[coordinator.model],
            name=coordinator.config_entry.title,
        )
