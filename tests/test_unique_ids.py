"""Fix 4: entry-scoped unique IDs and the v1 -> v2 registry migration."""
from types import SimpleNamespace

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ptv import async_migrate_entry
from custom_components.ptv.binary_sensor import PTVDelayBinarySensor
from custom_components.ptv.sensor import PTVMaxDelaySensor, PTVUpcomingTrainSensor


async def test_migrate_v1_prefixes_unique_ids(hass):
    entry = MockConfigEntry(domain="ptv", version=1, entry_id="entryA", title="A")
    other = MockConfigEntry(domain="ptv", version=1, entry_id="entryB", title="B")
    entry.add_to_hass(hass); other.add_to_hass(hass)
    reg = er.async_get(hass)
    a = reg.async_get_or_create("sensor", "ptv", "ptv_sunbury_max_delay",
                                config_entry=entry, suggested_object_id="outside_ptv_sunbury_line_max_delay")
    d = reg.async_get_or_create("sensor", "ptv", "ptv_sunbury_albion_citybound_1", config_entry=entry)
    b = reg.async_get_or_create("sensor", "ptv", "ptv_pakenham_max_delay", config_entry=other)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert reg.async_get(a.entity_id).unique_id == "entryA_ptv_sunbury_max_delay"
    assert a.entity_id == "sensor.outside_ptv_sunbury_line_max_delay"  # entity_id kept
    assert reg.async_get(d.entity_id).unique_id == "entryA_ptv_sunbury_albion_citybound_1"
    assert reg.async_get(b.entity_id).unique_id == "ptv_pakenham_max_delay"  # other entry untouched

    # Idempotent if run again
    assert await async_migrate_entry(hass, entry)
    assert reg.async_get(a.entity_id).unique_id == "entryA_ptv_sunbury_max_delay"


async def test_downgrade_refused(hass):
    entry = MockConfigEntry(domain="ptv", version=3, entry_id="x")
    entry.add_to_hass(hass)
    assert not await async_migrate_entry(hass, entry)


def _coord(entry_id):
    return SimpleNamespace(entry_id=entry_id, mode="train", data={}, gtfs_cache={},
                           async_add_listener=lambda *a, **k: (lambda: None))


async def test_two_entries_same_line_do_not_collide(hass):
    ids = set()
    for eid in ("e1", "e2"):
        c = _coord(eid)
        for ent in (PTVMaxDelaySensor(c, "Sunbury"), PTVDelayBinarySensor(c, "Sunbury"),
                    PTVUpcomingTrainSensor(c, "Sunbury", "Albion", "citybound", 1)):
            assert ent.unique_id.startswith(f"{eid}_ptv_sunbury")
            ids.add(ent.unique_id)
    assert len(ids) == 6
