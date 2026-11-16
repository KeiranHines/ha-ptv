"""Fix 3: per-direction delay/cancellation stats and entities."""
import time

from google.transit import gtfs_realtime_pb2

from custom_components.ptv import PTVDataCoordinator
from custom_components.ptv.binary_sensor import PTVCancellationBinarySensor, PTVDelayBinarySensor
from custom_components.ptv.sensor import (
    PTVMaxDelaySensor, PTVStatusSensor, configured_directions,
)

ROUTE = "aus:vic:vic-02-SUY:"


def _feed():
    f = gtfs_realtime_pb2.FeedMessage()
    f.header.gtfs_realtime_version = "2.0"
    now = int(time.time())
    for tid, stop, delay, cancelled in (
        ("T1", "15364", 400, False),   # citybound, 6.7 min late
        ("T2", "15365", 600, False),   # outbound, 10 min late
        ("T3", "15364", 0, True),      # citybound, cancelled
        ("T4", "15365", 0, False),     # outbound, on time
        ("T5", "99999", 900, False),   # direction unknown, 15 min late
    ):
        e = f.entity.add(); e.id = tid
        tu = e.trip_update; tu.trip.trip_id = tid; tu.trip.route_id = ROUTE
        if cancelled:
            tu.trip.schedule_relationship = 3
            continue
        # Then a final stop: citybound tunnel trips end at the Town Hall
        # handover, which the parser drops.
        for i, sid in enumerate((stop, "26553")):
            stu = tu.stop_time_update.add(); stu.stop_id = sid
            stu.departure.delay = delay; stu.departure.time = now + 600 * (i + 1) + delay
    return f.SerializeToString()


def _coordinator(hass, directions="both"):
    return PTVDataCoordinator(
        hass, api_key="x", monitored_lines=["Sunbury"], scan_interval=60,
        alert_effects=set(),
        stations_config=[{"name": "Albion", "directions": directions, "count": 4}],
        station_stop_ids={"albion": {"stop_ids": ["15364", "15365"]}},
        gtfs_cache={"trip_directions": {"T1": 1, "T2": 0, "T3": 1, "T4": 0},
                    "through_trips": {}, "scheduled_by_station": {}},
        mode="train",
    )


async def test_stats_split_by_direction(hass):
    c = _coordinator(hass)
    r = c._parse_all(_feed(), b"", b"")["Sunbury"]
    # Line totals unchanged in meaning: every own-line trip, incl. unknown direction
    assert (r["max_delay_seconds"], r["delay_count"], r["cancelled_trips"]) == (900, 3, ["T3"])
    cb, ob = r["by_direction"]["citybound"], r["by_direction"]["outbound"]
    assert (cb["max_delay_seconds"], cb["delay_count"], cb["cancelled_trips"]) == (400, 1, ["T3"])
    assert cb["has_delays"] and cb["has_cancellations"]
    assert (ob["max_delay_seconds"], ob["delay_count"], ob["cancelled_trips"]) == (600, 1, [])
    assert ob["has_delays"] and not ob["has_cancellations"]
    # Departures still bucketed by direction
    st = r["stations"]["albion"]
    assert [d["delay_sec"] for d in st["citybound"]] == [400]
    assert sorted(d["delay_sec"] for d in st["outbound"]) == [0, 600]


async def test_direction_entities(hass):
    c = _coordinator(hass)
    c.data = c._parse_all(_feed(), b"", b"")
    md = PTVMaxDelaySensor(c, "Sunbury", "citybound")
    assert md.unique_id == "ptv_sunbury_citybound_max_delay"
    assert md.name == "PTV Sunbury Line Citybound Max Delay"
    assert md.native_value == 6.7
    assert md.extra_state_attributes == {"direction": "citybound", "delay_count": 1, "cancelled_count": 1}
    assert PTVMaxDelaySensor(c, "Sunbury", "outbound").native_value == 10.0
    assert PTVMaxDelaySensor(c, "Sunbury").native_value == 15.0  # line-wide unchanged
    assert PTVMaxDelaySensor(c, "Sunbury").extra_state_attributes is None

    s = PTVStatusSensor(c, "Sunbury", "citybound")
    assert s.unique_id == "ptv_sunbury_citybound_status"
    assert s.native_value.startswith("Sunbury citybound: 1 cancelled; delays up to 7 min; ")
    assert s.icon == "mdi:train-car-remove"
    so = PTVStatusSensor(c, "Sunbury", "outbound")
    assert so.native_value.startswith("Sunbury outbound: delays up to 10 min; ")
    assert so.icon == "mdi:train-alert"

    d = PTVDelayBinarySensor(c, "Sunbury", "outbound")
    assert (d.unique_id, d.name, d.is_on) == ("ptv_sunbury_outbound_delays", "PTV Sunbury Line Outbound Delays", True)
    assert d.extra_state_attributes == {"delay_count": 1, "max_delay_minutes": 10.0}
    x = PTVCancellationBinarySensor(c, "Sunbury", "outbound")
    assert (x.unique_id, x.is_on) == ("ptv_sunbury_outbound_cancellations", False)
    assert PTVCancellationBinarySensor(c, "Sunbury", "citybound").is_on
    # Existing line entities keep their IDs and names
    assert PTVDelayBinarySensor(c, "Sunbury").unique_id == "ptv_sunbury_delays"
    assert PTVStatusSensor(c, "Sunbury").name == "PTV Sunbury Line Status"


async def test_running_normally(hass):
    c = _coordinator(hass)
    c.data = c._parse_all(b"", b"", b"")
    assert PTVStatusSensor(c, "Sunbury", "outbound").native_value == "Sunbury outbound: running normally"


def test_configured_directions():
    cfg = lambda *ds: [{"name": f"S{i}", "directions": d} for i, d in enumerate(ds)]
    assert configured_directions(cfg("citybound")) == ["citybound"]
    assert configured_directions(cfg("outbound", "citybound")) == ["citybound", "outbound"]
    assert configured_directions(cfg("both")) == ["citybound", "outbound"]
    assert configured_directions([]) == []


async def test_tram_direction_names(hass):
    c = PTVDataCoordinator(
        hass, api_key="x", monitored_lines=["Route 96"], scan_interval=60, alert_effects=set(),
        stations_config=[{"name": "Stop A", "directions": "both", "count": 2}],
        station_stop_ids={"stop a": {"stop_ids": ["1"]}},
        gtfs_cache={"trip_directions": {}, "through_trips": {}, "scheduled_by_station": {},
                    "direction_labels": {"aus:vic:vic-03-96:": {"0": "East Brunswick", "1": "St Kilda Beach"}}},
        mode="tram",
    )
    c.data = c._parse_all(b"", b"", b"")
    assert PTVMaxDelaySensor(c, "Route 96", "outbound").name == "PTV Route 96 To East Brunswick Max Delay"
    assert PTVStatusSensor(c, "Route 96", "citybound").native_value == "Route 96 to St Kilda Beach: running normally"
    assert PTVDelayBinarySensor(c, "Route 96", "citybound").name == "PTV Route 96 To St Kilda Beach Delays"
