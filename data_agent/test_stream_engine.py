"""
Tests for real-time data stream processing engine.

Covers: spatial utilities, in-memory buffer, stream lifecycle,
windowed aggregation, geofence checking, trajectory building,
WebSocket subscription, and tool functions.
"""
import asyncio
import json
import math
import time
import unittest

from data_agent.stream_engine import (
    LocationEvent, StreamConfig, WindowResult,
    InMemoryBuffer, StreamEngine,
    haversine_meters, compute_heading, check_geofence,
    build_trajectory, detect_clusters,
    get_stream_engine,
)
from data_agent.stream_tools import (
    create_iot_stream, list_active_streams,
    stop_data_stream, get_stream_statistics,
    set_geofence_alert,
)


# ---------------------------------------------------------------------------
# Spatial Utilities
# ---------------------------------------------------------------------------

class TestHaversine(unittest.TestCase):
    def test_same_point(self):
        d = haversine_meters(39.9, 116.4, 39.9, 116.4)
        self.assertAlmostEqual(d, 0, places=1)

    def test_known_distance(self):
        """Beijing to Shanghai ≈ 1068 km."""
        d = haversine_meters(39.9042, 116.4074, 31.2304, 121.4737)
        self.assertAlmostEqual(d / 1000, 1068, delta=50)

    def test_short_distance(self):
        """~111 km per degree of latitude."""
        d = haversine_meters(0, 0, 1, 0)
        self.assertAlmostEqual(d / 1000, 111, delta=2)


class TestComputeHeading(unittest.TestCase):
    def test_north(self):
        h = compute_heading(0, 0, 1, 0)
        self.assertAlmostEqual(h, 0, delta=1)

    def test_east(self):
        h = compute_heading(0, 0, 0, 1)
        self.assertAlmostEqual(h, 90, delta=1)

    def test_range(self):
        h = compute_heading(0, 0, -1, -1)
        self.assertTrue(0 <= h < 360)


class TestGeofence(unittest.TestCase):
    def test_inside(self):
        wkt = "POLYGON((116 39, 117 39, 117 40, 116 40, 116 39))"
        self.assertTrue(check_geofence(39.5, 116.5, wkt))

    def test_outside(self):
        wkt = "POLYGON((116 39, 117 39, 117 40, 116 40, 116 39))"
        self.assertFalse(check_geofence(41.0, 116.5, wkt))

    def test_empty_geofence_always_true(self):
        self.assertTrue(check_geofence(0, 0, ""))

    def test_invalid_wkt_returns_true(self):
        self.assertTrue(check_geofence(0, 0, "NOT_VALID_WKT"))


# ---------------------------------------------------------------------------
# Trajectory Building
# ---------------------------------------------------------------------------

class TestBuildTrajectory(unittest.TestCase):
    def test_empty_events(self):
        result = build_trajectory([])
        self.assertEqual(result["geometry"]["coordinates"], [])

    def test_single_event(self):
        events = [LocationEvent("d1", "s1", 39.9, 116.4, time.time())]
        result = build_trajectory(events)
        self.assertEqual(len(result["geometry"]["coordinates"]), 1)

    def test_multiple_events_ordered(self):
        t = time.time()
        events = [
            LocationEvent("d1", "s1", 39.9, 116.4, t + 2),
            LocationEvent("d1", "s1", 39.91, 116.41, t),
            LocationEvent("d1", "s1", 39.92, 116.42, t + 1),
        ]
        result = build_trajectory(events)
        coords = result["geometry"]["coordinates"]
        self.assertEqual(len(coords), 3)
        # Should be sorted by timestamp
        self.assertAlmostEqual(coords[0][1], 39.91, places=2)

    def test_has_distance(self):
        t = time.time()
        events = [
            LocationEvent("d1", "s1", 0, 0, t),
            LocationEvent("d1", "s1", 0, 1, t + 10),
        ]
        result = build_trajectory(events)
        self.assertGreater(result["properties"]["total_distance_m"], 100000)


# ---------------------------------------------------------------------------
# Cluster Detection
# ---------------------------------------------------------------------------

class TestDetectClusters(unittest.TestCase):
    def test_too_few_events(self):
        events = [LocationEvent("d1", "s1", 39.9, 116.4, time.time())]
        self.assertEqual(detect_clusters(events), [])

    def test_clustered_events(self):
        """Multiple events at same location should form a cluster."""
        t = time.time()
        events = [
            LocationEvent(f"d{i}", "s1", 39.9 + i * 0.0001, 116.4, t)
            for i in range(10)
        ]
        clusters = detect_clusters(events, eps_meters=5000, min_samples=3)
        # Should find at least one cluster
        self.assertGreater(len(clusters), 0)


# ---------------------------------------------------------------------------
# InMemoryBuffer
# ---------------------------------------------------------------------------

class TestInMemoryBuffer(unittest.TestCase):
    def test_push_and_read(self):
        buf = InMemoryBuffer()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(buf.push("s1", {"timestamp": time.time(), "data": "x"}))
        result = loop.run_until_complete(buf.read_window("s1", 60))
        self.assertEqual(len(result), 1)

    def test_window_filter(self):
        buf = InMemoryBuffer()
        loop = asyncio.new_event_loop()
        # Old event (should be filtered out)
        loop.run_until_complete(buf.push("s1", {"timestamp": time.time() - 120, "data": "old"}))
        # Recent event
        loop.run_until_complete(buf.push("s1", {"timestamp": time.time(), "data": "new"}))
        result = loop.run_until_complete(buf.read_window("s1", 60))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["data"], "new")

    def test_clear(self):
        buf = InMemoryBuffer()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(buf.push("s1", {"timestamp": time.time()}))
        loop.run_until_complete(buf.clear("s1"))
        result = loop.run_until_complete(buf.read_window("s1", 60))
        self.assertEqual(len(result), 0)

    def test_max_events_cap(self):
        buf = InMemoryBuffer(max_events_per_stream=5)
        loop = asyncio.new_event_loop()
        for i in range(10):
            loop.run_until_complete(buf.push("s1", {"timestamp": time.time(), "i": i}))
        self.assertTrue(len(buf._streams["s1"]) <= 5)


# ---------------------------------------------------------------------------
# StreamEngine
# ---------------------------------------------------------------------------

class TestStreamEngine(unittest.TestCase):
    def setUp(self):
        self.engine = StreamEngine()

    def test_create_stream(self):
        config = self.engine.create_stream(StreamConfig(
            id="", name="Test Stream", window_seconds=10,
        ))
        self.assertIsNotNone(config.id)
        self.assertEqual(config.name, "Test Stream")

    def test_get_active_streams(self):
        self.engine.create_stream(StreamConfig(id="", name="S1"))
        self.engine.create_stream(StreamConfig(id="", name="S2"))
        streams = self.engine.get_active_streams()
        self.assertEqual(len(streams), 2)

    def test_start_and_stop_stream(self):
        config = self.engine.create_stream(StreamConfig(id="", name="X", window_seconds=1))
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.engine.start_stream(config.id))
        self.assertIn(config.id, self.engine._running_tasks)
        loop.run_until_complete(self.engine.stop_stream(config.id))
        self.assertNotIn(config.id, self.engine._running_tasks)

    def test_ingest_event(self):
        config = self.engine.create_stream(StreamConfig(id="", name="Y"))
        event = LocationEvent("d1", config.id, 39.9, 116.4, time.time())
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.engine.ingest(event))
        self.assertTrue(result)

    def test_process_window_empty(self):
        config = self.engine.create_stream(StreamConfig(id="", name="Z", window_seconds=60))
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(self.engine.process_window(config.id))
        self.assertIsNotNone(result)
        self.assertEqual(result.event_count, 0)

    def test_process_window_with_events(self):
        config = self.engine.create_stream(StreamConfig(id="", name="W", window_seconds=60))
        loop = asyncio.new_event_loop()
        for i in range(5):
            event = LocationEvent(f"d{i}", config.id, 39.9 + i * 0.01, 116.4, time.time())
            loop.run_until_complete(self.engine.ingest(event))

        result = loop.run_until_complete(self.engine.process_window(config.id))
        self.assertEqual(result.event_count, 5)
        self.assertEqual(result.device_count, 5)
        self.assertGreater(result.centroid_lat, 39)

    def test_geofence_alerts(self):
        geofence = "POLYGON((116 39, 117 39, 117 40, 116 40, 116 39))"
        config = self.engine.create_stream(StreamConfig(
            id="", name="Geo", window_seconds=60, geofence_wkt=geofence,
        ))
        loop = asyncio.new_event_loop()
        # Inside geofence
        loop.run_until_complete(self.engine.ingest(
            LocationEvent("d1", config.id, 39.5, 116.5, time.time())
        ))
        # Outside geofence
        loop.run_until_complete(self.engine.ingest(
            LocationEvent("d2", config.id, 41.0, 116.5, time.time())
        ))
        result = loop.run_until_complete(self.engine.process_window(config.id))
        self.assertGreater(len(result.alerts), 0)
        self.assertEqual(result.alerts[0]["device_id"], "d2")


# ---------------------------------------------------------------------------
# Subscription / Broadcast
# ---------------------------------------------------------------------------

class TestSubscription(unittest.TestCase):
    def test_subscribe_unsubscribe(self):
        engine = StreamEngine()
        q = engine.subscribe("s1")
        self.assertEqual(len(engine._subscribers["s1"]), 1)
        engine.unsubscribe("s1", q)
        self.assertEqual(len(engine._subscribers["s1"]), 0)

    def test_broadcast_delivers_to_queue(self):
        engine = StreamEngine()
        q = engine.subscribe("s1")
        result = WindowResult(
            stream_id="s1", window_start=0, window_end=1,
            event_count=1, features=[{"type": "Feature", "geometry": {}}],
        )
        loop = asyncio.new_event_loop()
        loop.run_until_complete(engine._broadcast("s1", result))
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        data = json.loads(msg)
        self.assertEqual(data["type"], "FeatureCollection")


# ---------------------------------------------------------------------------
# Tool Functions
# ---------------------------------------------------------------------------

class TestStreamTools(unittest.TestCase):
    def test_create_iot_stream(self):
        result = create_iot_stream("测试流", window_seconds=30)
        self.assertEqual(result["status"], "success")
        self.assertIn("stream_id", result)
        self.assertEqual(result["window_seconds"], 30)

    def test_list_active_streams(self):
        # Create one first
        create_iot_stream("列表测试")
        result = list_active_streams()
        self.assertEqual(result["status"], "success")
        self.assertGreater(result["count"], 0)

    def test_set_geofence_valid(self):
        r = create_iot_stream("围栏测试")
        sid = r["stream_id"]
        result = set_geofence_alert(sid, "POLYGON((116 39, 117 39, 117 40, 116 40, 116 39))")
        self.assertEqual(result["status"], "success")

    def test_set_geofence_nonexistent_stream(self):
        result = set_geofence_alert("nonexistent_id", "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))")
        self.assertEqual(result["status"], "error")

    def test_window_seconds_clamped(self):
        result = create_iot_stream("Clamp", window_seconds=1)
        self.assertEqual(result["window_seconds"], 5)  # Min clamp
        result2 = create_iot_stream("Clamp2", window_seconds=9999)
        self.assertEqual(result2["window_seconds"], 3600)  # Max clamp


# ---------------------------------------------------------------------------
# Stream API route list
# ---------------------------------------------------------------------------

class TestStreamRoutes(unittest.TestCase):
    def test_get_routes(self):
        from data_agent.stream_api import get_stream_routes
        routes = get_stream_routes()
        paths = [r.path for r in routes]
        self.assertIn("/api/streams", paths)
        self.assertIn("/api/streams/{id}", paths)
        self.assertIn("/api/streams/{id}/ingest", paths)
        self.assertIn("/ws/streams/{id}", paths)

    def test_mount_routes(self):
        from data_agent.stream_api import mount_stream_routes
        from unittest.mock import MagicMock
        app = MagicMock()
        app.router.routes = []
        result = mount_stream_routes(app)
        self.assertTrue(result)
        self.assertEqual(len(app.router.routes), 5)


if __name__ == "__main__":
    unittest.main()
