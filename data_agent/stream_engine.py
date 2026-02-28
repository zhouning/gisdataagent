"""
Real-time data stream processing engine for GIS Data Agent.

Provides spatial streaming capabilities:
- Redis Streams as message queue (graceful fallback to in-memory)
- Windowed spatial aggregation (tumbling windows)
- Geofence check (point-in-polygon)
- Trajectory building (ordered points → LineString)
- Speed/heading computation
- Moving cluster detection (DBSCAN)

Feature activates only when Redis is available.
Without Redis, uses an in-memory buffer (single-node only).
"""
import asyncio
import json
import math
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

try:
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class LocationEvent:
    """A single location update from a device."""
    device_id: str
    stream_id: str
    lat: float
    lng: float
    timestamp: float  # Unix epoch
    speed: float = 0.0
    heading: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)
    owner_username: str = ""


@dataclass
class StreamConfig:
    """Configuration for a data stream."""
    id: str
    name: str
    geofence_wkt: str = ""
    window_seconds: int = 60
    status: str = "active"
    owner_username: str = ""
    created_at: float = 0.0


@dataclass
class WindowResult:
    """Result of a windowed aggregation."""
    stream_id: str
    window_start: float
    window_end: float
    event_count: int = 0
    device_count: int = 0
    centroid_lat: float = 0.0
    centroid_lng: float = 0.0
    spatial_spread: float = 0.0  # std dev in meters
    alerts: List[Dict] = field(default_factory=list)
    features: List[Dict] = field(default_factory=list)  # GeoJSON features


# ---------------------------------------------------------------------------
# Spatial Utilities
# ---------------------------------------------------------------------------

def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_heading(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute bearing in degrees (0-360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lng2 - lng1)
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def check_geofence(lat: float, lng: float, geofence_wkt: str) -> bool:
    """Check if a point is inside a geofence polygon."""
    if not HAS_SHAPELY or not geofence_wkt:
        return True  # No geofence = always inside
    try:
        from shapely import wkt
        polygon = wkt.loads(geofence_wkt)
        prepared = prep(polygon)
        return prepared.contains(Point(lng, lat))
    except Exception:
        return True


def build_trajectory(events: List[LocationEvent]) -> Dict:
    """Build GeoJSON LineString from ordered events."""
    if not events:
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": []}, "properties": {}}

    sorted_events = sorted(events, key=lambda e: e.timestamp)
    coords = [[e.lng, e.lat] for e in sorted_events]
    total_dist = 0
    for i in range(1, len(sorted_events)):
        total_dist += haversine_meters(
            sorted_events[i - 1].lat, sorted_events[i - 1].lng,
            sorted_events[i].lat, sorted_events[i].lng
        )
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "device_id": sorted_events[0].device_id,
            "point_count": len(coords),
            "total_distance_m": round(total_dist, 1),
            "start_time": datetime.fromtimestamp(sorted_events[0].timestamp, tz=timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(sorted_events[-1].timestamp, tz=timezone.utc).isoformat(),
        },
    }


def detect_clusters(events: List[LocationEvent], eps_meters: float = 500, min_samples: int = 3) -> List[Dict]:
    """Detect spatial clusters using DBSCAN on latest window."""
    if len(events) < min_samples:
        return []
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN

        coords = np.array([[e.lat, e.lng] for e in events])
        # Convert eps from meters to approximate degrees
        eps_deg = eps_meters / 111000
        db = DBSCAN(eps=eps_deg, min_samples=min_samples, metric='euclidean')
        labels = db.fit_predict(coords)

        clusters = []
        for label in set(labels):
            if label == -1:
                continue
            mask = labels == label
            cluster_coords = coords[mask]
            centroid = cluster_coords.mean(axis=0)
            clusters.append({
                "cluster_id": int(label),
                "centroid_lat": round(float(centroid[0]), 6),
                "centroid_lng": round(float(centroid[1]), 6),
                "point_count": int(mask.sum()),
                "device_ids": list({events[i].device_id for i, m in enumerate(mask) if m}),
            })
        return clusters
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# In-Memory Buffer (fallback when Redis unavailable)
# ---------------------------------------------------------------------------

class InMemoryBuffer:
    """Simple in-memory stream buffer for single-node deployments."""

    def __init__(self, max_events_per_stream: int = 10000):
        self._streams: Dict[str, List[Dict]] = defaultdict(list)
        self._max = max_events_per_stream
        self._lock = asyncio.Lock()

    async def push(self, stream_id: str, event_data: Dict) -> None:
        async with self._lock:
            buf = self._streams[stream_id]
            buf.append(event_data)
            if len(buf) > self._max:
                self._streams[stream_id] = buf[-self._max:]

    async def read_window(self, stream_id: str, window_seconds: int) -> List[Dict]:
        async with self._lock:
            cutoff = time.time() - window_seconds
            return [e for e in self._streams.get(stream_id, []) if float(e.get("timestamp", 0)) > cutoff]

    async def clear(self, stream_id: str) -> None:
        async with self._lock:
            self._streams.pop(stream_id, None)


# ---------------------------------------------------------------------------
# Stream Engine
# ---------------------------------------------------------------------------

class StreamEngine:
    """Core stream processing engine.

    Uses Redis Streams if available, falls back to in-memory buffer.
    """

    def __init__(self):
        self._redis: Optional[Any] = None
        self._buffer = InMemoryBuffer()
        self._configs: Dict[str, StreamConfig] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._use_redis = False

    async def initialize(self) -> bool:
        """Connect to Redis if available."""
        if not HAS_REDIS:
            print("[Stream] redis.asyncio not installed. Using in-memory buffer.")
            return False

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            self._use_redis = True
            print(f"[Stream] Connected to Redis at {redis_url}")
            return True
        except Exception as e:
            print(f"[Stream] Redis unavailable ({e}). Using in-memory buffer.")
            self._redis = None
            self._use_redis = False
            return False

    async def close(self):
        """Shutdown: stop all streams and close Redis."""
        for stream_id in list(self._running_tasks.keys()):
            await self.stop_stream(stream_id)
        if self._redis:
            await self._redis.aclose()

    # ---- Stream Lifecycle ----------------------------------------------------

    def create_stream(self, config: StreamConfig) -> StreamConfig:
        """Register a new stream configuration."""
        if not config.id:
            config.id = uuid.uuid4().hex[:12]
        config.created_at = time.time()
        self._configs[config.id] = config
        return config

    async def start_stream(self, stream_id: str) -> bool:
        """Start processing a stream (background windowed aggregation)."""
        config = self._configs.get(stream_id)
        if not config:
            return False
        if stream_id in self._running_tasks:
            return True  # Already running

        config.status = "active"
        task = asyncio.create_task(self._process_loop(stream_id))
        self._running_tasks[stream_id] = task
        return True

    async def stop_stream(self, stream_id: str) -> bool:
        """Stop a running stream."""
        task = self._running_tasks.pop(stream_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        config = self._configs.get(stream_id)
        if config:
            config.status = "stopped"

        if self._use_redis:
            # Clean up Redis stream
            try:
                await self._redis.delete(f"stream:{stream_id}")
            except Exception:
                pass
        else:
            await self._buffer.clear(stream_id)

        return True

    def get_active_streams(self) -> List[Dict]:
        """List all registered streams."""
        return [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status,
                "window_seconds": c.window_seconds,
                "has_geofence": bool(c.geofence_wkt),
                "owner": c.owner_username,
            }
            for c in self._configs.values()
        ]

    # ---- Ingest ---------------------------------------------------------------

    async def ingest(self, event: LocationEvent) -> bool:
        """Push a location event into the stream."""
        data = {
            "device_id": event.device_id,
            "stream_id": event.stream_id,
            "lat": str(event.lat),
            "lng": str(event.lng),
            "timestamp": str(event.timestamp or time.time()),
            "speed": str(event.speed),
            "heading": str(event.heading),
            "payload": json.dumps(event.payload),
            "owner": event.owner_username,
        }

        if self._use_redis:
            try:
                await self._redis.xadd(
                    f"stream:{event.stream_id}",
                    data,
                    maxlen=10000,
                )
            except Exception as e:
                print(f"[Stream] Redis xadd failed: {e}")
                await self._buffer.push(event.stream_id, data)
        else:
            await self._buffer.push(event.stream_id, data)

        return True

    # ---- Processing Loop ------------------------------------------------------

    async def _process_loop(self, stream_id: str):
        """Background: windowed aggregation loop."""
        config = self._configs.get(stream_id)
        if not config:
            return

        while True:
            try:
                await asyncio.sleep(config.window_seconds)
                result = await self.process_window(stream_id)
                if result and result.event_count > 0:
                    await self._broadcast(stream_id, result)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Stream] Processing error for {stream_id}: {e}")

    async def process_window(self, stream_id: str) -> Optional[WindowResult]:
        """Aggregate events in the current window."""
        config = self._configs.get(stream_id)
        if not config:
            return None

        # Read events
        if self._use_redis:
            raw_events = await self._read_redis_window(stream_id, config.window_seconds)
        else:
            raw_events = await self._buffer.read_window(stream_id, config.window_seconds)

        if not raw_events:
            return WindowResult(
                stream_id=stream_id,
                window_start=time.time() - config.window_seconds,
                window_end=time.time(),
            )

        # Parse events
        events = []
        for raw in raw_events:
            try:
                events.append(LocationEvent(
                    device_id=raw.get("device_id", ""),
                    stream_id=stream_id,
                    lat=float(raw.get("lat", 0)),
                    lng=float(raw.get("lng", 0)),
                    timestamp=float(raw.get("timestamp", 0)),
                    speed=float(raw.get("speed", 0)),
                    heading=float(raw.get("heading", 0)),
                    payload=json.loads(raw.get("payload", "{}")),
                    owner_username=raw.get("owner", ""),
                ))
            except (ValueError, TypeError):
                continue

        if not events:
            return WindowResult(
                stream_id=stream_id,
                window_start=time.time() - config.window_seconds,
                window_end=time.time(),
            )

        # Aggregate
        now = time.time()
        lats = [e.lat for e in events]
        lngs = [e.lng for e in events]
        centroid_lat = sum(lats) / len(lats)
        centroid_lng = sum(lngs) / len(lngs)

        # Spatial spread (std dev of distances from centroid)
        dists = [haversine_meters(centroid_lat, centroid_lng, e.lat, e.lng) for e in events]
        spread = (sum(d ** 2 for d in dists) / len(dists)) ** 0.5 if dists else 0

        # Build GeoJSON features (one per device trajectory)
        device_events: Dict[str, List[LocationEvent]] = defaultdict(list)
        for e in events:
            device_events[e.device_id].append(e)

        features = []
        for dev_id, dev_events in device_events.items():
            if len(dev_events) >= 2:
                features.append(build_trajectory(dev_events))
            else:
                # Single point
                e = dev_events[0]
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [e.lng, e.lat]},
                    "properties": {"device_id": e.device_id, "speed": e.speed},
                })

        # Geofence alerts
        alerts = []
        if config.geofence_wkt:
            for e in events:
                if not check_geofence(e.lat, e.lng, config.geofence_wkt):
                    alerts.append({
                        "type": "geofence_exit",
                        "device_id": e.device_id,
                        "lat": e.lat,
                        "lng": e.lng,
                        "timestamp": e.timestamp,
                    })

        return WindowResult(
            stream_id=stream_id,
            window_start=now - config.window_seconds,
            window_end=now,
            event_count=len(events),
            device_count=len(device_events),
            centroid_lat=round(centroid_lat, 6),
            centroid_lng=round(centroid_lng, 6),
            spatial_spread=round(spread, 1),
            alerts=alerts,
            features=features,
        )

    async def _read_redis_window(self, stream_id: str, window_seconds: int) -> List[Dict]:
        """Read events from Redis Stream within time window."""
        if not self._redis:
            return []
        try:
            # Use XREVRANGE to get latest events
            min_id = str(int((time.time() - window_seconds) * 1000)) + "-0"
            entries = await self._redis.xrange(f"stream:{stream_id}", min=min_id)
            return [data for _, data in entries]
        except Exception as e:
            print(f"[Stream] Redis read error: {e}")
            return []

    # ---- WebSocket Broadcast --------------------------------------------------

    def subscribe(self, stream_id: str) -> asyncio.Queue:
        """Subscribe to stream updates. Returns a queue for receiving results."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers[stream_id].append(q)
        return q

    def unsubscribe(self, stream_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from stream updates."""
        subs = self._subscribers.get(stream_id, [])
        if queue in subs:
            subs.remove(queue)

    async def _broadcast(self, stream_id: str, result: WindowResult) -> None:
        """Broadcast window result to all subscribers."""
        geojson = {
            "type": "FeatureCollection",
            "features": result.features,
            "properties": {
                "stream_id": result.stream_id,
                "window_start": result.window_start,
                "window_end": result.window_end,
                "event_count": result.event_count,
                "device_count": result.device_count,
                "centroid": [result.centroid_lng, result.centroid_lat],
                "spatial_spread_m": result.spatial_spread,
                "alerts": result.alerts,
            },
        }
        message = json.dumps(geojson)

        dead_queues = []
        for q in self._subscribers.get(stream_id, []):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dead_queues.append(q)

        for q in dead_queues:
            self.unsubscribe(stream_id, q)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[StreamEngine] = None


def get_stream_engine() -> StreamEngine:
    """Get or create the singleton StreamEngine."""
    global _engine
    if _engine is None:
        _engine = StreamEngine()
    return _engine


async def ensure_stream_engine() -> StreamEngine:
    """Initialize the stream engine (connect to Redis if available)."""
    engine = get_stream_engine()
    await engine.initialize()
    return engine
