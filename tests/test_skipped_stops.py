"""Fix 6: stations left out of a trip update take the previous stop's delay."""
import time
from datetime import datetime

from google.transit import gtfs_realtime_pb2

from custom_components.ptv import PTVDataCoordinator

ROUTE = "aus:vic:vic-02-SUY:"


def _secs_since_midnight(ts):
    d = datetime.fromtimestamp(ts).astimezone()
    return d.hour * 3600 + d.minute * 60 + d.second


def _setup(hass, stops, albion_seq=7, albion_dir=1, sched_in=1200):
    """stops: [(stop_sequence, stop_id, delay, minutes_from_now)] for trip T1."""
    now = int(time.time())
    f = gtfs_realtime_pb2.FeedMessage(); f.header.gtfs_realtime_version = "2.0"
    e = f.entity.add(); e.id = "T1"
    tu = e.trip_update; tu.trip.trip_id = "T1"; tu.trip.route_id = ROUTE
    for seq, sid, delay, mins in stops:
        s = tu.stop_time_update.add(); s.stop_sequence = seq; s.stop_id = sid
        s.departure.delay = delay; s.departure.time = now + mins * 60 + delay
    sched = now + sched_in
    c = PTVDataCoordinator(
        hass, api_key="x", monitored_lines=["Sunbury"], scan_interval=60, alert_effects=set(),
        stations_config=[{"name": "Albion", "directions": "both", "count": 4}],
        station_stop_ids={"albion": {"stop_ids": ["15364", "15365"]}},
        gtfs_cache={
            "trip_directions": {"T1": 1}, "through_trips": {},
            "scheduled_by_station": {"albion": [{
                "trip_id": "T1", "stop_id": "15364", "stop_sequence": albion_seq,
                "direction_id": albion_dir, "dep_seconds": _secs_since_midnight(sched),
                "dep_str": "",
            }]},
        },
        mode="train",
    )
    return c, f.SerializeToString(), sched


def _citybound(c, raw):
    return c._parse_all(raw, b"", b"")["Sunbury"]["stations"]["albion"]["citybound"]


# Z126 on 2026-11-16: updates at seqs 1-4, 6, 8-10, 12-15; Albion is seq 7.
Z126 = [(4, "15358", 120, 5), (6, "15362", 120, 10), (8, "26530", 180, 25), (15, "26553", 120, 40)]


async def test_gap_filled_with_previous_delay(hass):
    c, raw, sched = _setup(hass, Z126)
    deps = _citybound(c, raw)
    assert deps[0]["is_realtime"] and deps[0]["delay_sec"] == 120
    assert int(datetime.fromisoformat(deps[0]["dt_iso"]).timestamp()) == sched + 120


async def test_station_reported_directly_unchanged(hass):
    stops = [(6, "15362", 120, 10), (7, "15364", 60, 20), (8, "26530", 180, 25), (15, "26553", 120, 40)]
    c, raw, _ = _setup(hass, stops)
    deps = _citybound(c, raw)
    assert deps[0]["is_realtime"] and deps[0]["delay_sec"] == 60


async def test_not_filled_without_updates_on_both_sides(hass):
    # Albion after the last update (excluding the dropped Town Hall handover):
    # the train may no longer call there, so stay with the timetable.
    c, raw, _ = _setup(hass, [(4, "15358", 120, 5), (6, "15362", 120, 10), (15, "26553", 120, 40)],
                       albion_seq=16)
    deps = _citybound(c, raw)
    assert deps and not deps[0]["is_realtime"]
    # Albion before the first update: the train has already passed it.
    c, raw, _ = _setup(hass, Z126[1:], albion_seq=2)
    assert not any(d["is_realtime"] for d in _citybound(c, raw))


async def test_not_filled_for_other_direction(hass):
    c, raw, _ = _setup(hass, Z126, albion_dir=0)
    assert not any(d["is_realtime"] for d in _citybound(c, raw))


async def test_not_filled_if_estimate_in_past(hass):
    c, raw, _ = _setup(hass, Z126, sched_in=-600)
    assert not any(d["is_realtime"] for d in _citybound(c, raw))
