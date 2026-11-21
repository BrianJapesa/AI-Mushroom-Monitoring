"""Persistent threshold, contamination, escalation, and stale-sensor alerts."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Lock, Thread, current_thread
from typing import Any
from weakref import WeakKeyDictionary

from .db import Database

LOGGER = logging.getLogger(__name__)
_MONITOR_LOCK = Lock()
_MONITORS: WeakKeyDictionary[Any, Any] = WeakKeyDictionary()


class AlertEngine:
    """Create deduplicated alerts and persist active state across process restarts."""

    def __init__(
        self,
        database: Database,
        settings: Any,
        clock: Callable[[], datetime] | None = None,
        notify: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.notify = notify
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._owns_monitor = False
        self._started_at = self._now()

    @property
    def monitor_running(self) -> bool:
        """Return whether the background stale-sensor monitor is alive."""
        return bool(self._thread and self._thread.is_alive())

    def process_reading(
        self,
        reading: dict[str, Any],
        record_path: str | None = None,
        record: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Persist a reading's threshold alerts, recovery, and sensor-online state."""
        created: list[dict[str, Any]] = []
        callbacks: list[dict[str, Any]] = []
        with self._lock:
            state = self._load_state()
            state["last_sensor_ts"] = self._now_text()
            active_states = state["alert_state"]
            cooldowns = state["alert_cooldowns"]
            writes: dict[str, Any] = {"meta/state": state}
            if record_path and record is not None:
                writes["sensors/latest"] = reading
                writes[record_path] = record

            offline = state.get("sensor_offline")
            if isinstance(offline, dict):
                recovered = self._make_alert(
                    reading,
                    "sensor-online",
                    "Sensor readings have resumed.",
                    "low",
                    "resolved",
                )
                self._resolve_existing(offline.get("alert_id"), writes)
                self._queue_alert(recovered, writes)
                callbacks.append(recovered)
                state["sensor_offline"] = None

            checks = (
                (
                    "temperature-low",
                    "temperature",
                    reading["temperature"],
                    self.settings.temp_min,
                    "low",
                    "Temperature is below the room target.",
                ),
                (
                    "temperature-high",
                    "temperature",
                    reading["temperature"],
                    self.settings.temp_max,
                    "high",
                    "Temperature is above the room target.",
                ),
                (
                    "humidity-low",
                    "humidity",
                    reading["humidity"],
                    self.settings.hum_min,
                    "low",
                    "Humidity is below the room target.",
                ),
                (
                    "humidity-high",
                    "humidity",
                    reading["humidity"],
                    self.settings.hum_max,
                    "high",
                    "Humidity is above the room target.",
                ),
            )
            for kind, metric, value, threshold, direction, message in checks:
                state_key = f"{kind}|{reading['room']}"
                active = active_states.get(state_key)
                outside = value < threshold if direction == "low" else value > threshold
                margin = (
                    self.settings.recovery_margin_temp
                    if metric == "temperature"
                    else self.settings.recovery_margin_humidity
                )
                recovered = (
                    value >= threshold + margin
                    if direction == "low"
                    else value <= threshold - margin
                )
                if isinstance(active, dict) and recovered:
                    self._resolve_existing(active.get("alert_id"), writes)
                    info = self._make_alert(
                        reading,
                        f"{kind}-recovered",
                        f"{metric.title()} is back in its safe range.",
                        "low",
                        "resolved",
                    )
                    self._queue_alert(info, writes)
                    created.append(info)
                    callbacks.append(info)
                    active_states.pop(state_key, None)
                elif not active and outside:
                    dedupe_key = f"{kind}|{reading['room']}|med"
                    if not self._cooldown_ready(cooldowns.get(dedupe_key)):
                        continue
                    alert = self._make_alert(reading, kind, message, "med", "open")
                    alert.update({"value": float(value), "threshold": float(threshold)})
                    alert_id = self._queue_alert(alert, writes)
                    active_states[state_key] = {
                        "alert_id": alert_id,
                        "raised_at": alert["timestamp"],
                        "level": "med",
                        "escalated": False,
                    }
                    cooldowns[dedupe_key] = alert["timestamp"]
                    created.append(alert)
                    callbacks.append(alert)

            state["alert_state"] = active_states
            state["alert_cooldowns"] = cooldowns
            writes["meta/state"] = state
            self.database.update(writes)
        self._dispatch(callbacks)
        return created

    def process_prediction(
        self,
        bag: dict[str, Any],
        history_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Raise one contamination alert per bag/status and a recovery entry."""
        status = bag.get("status")
        if status not in {"healthy", "suspect", "contaminated"}:
            return []
        bag_id = str(bag["id"])
        alert: dict[str, Any] | None = None
        with self._lock:
            state = self._load_state()
            bags = state["bag_alert_state"]
            writes: dict[str, Any] = {f"bags/{bag_id}": bag}
            if history_path:
                writes[history_path] = bag
            previous = bags.get(bag_id)
            previous_status = (
                previous.get("status") if isinstance(previous, dict) else previous
            )
            if status in {"suspect", "contaminated"} and previous_status != status:
                level = "high" if status == "contaminated" else "med"
                alert = self._make_alert(
                    bag,
                    f"contamination-{status}",
                    f"Bag {bag_id} needs a staff check.",
                    level,
                    "open" if status == "contaminated" else "review",
                )
                alert.update({"bag_id": bag_id, "confidence": bag.get("confidence")})
                writes["meta/state"] = state
                if isinstance(previous, dict):
                    self._resolve_existing(previous.get("alert_id"), writes)
                alert_id = self._queue_alert(alert, writes)
                bags[bag_id] = {"status": status, "alert_id": alert_id}
                state["bag_alert_state"] = bags
                writes["meta/state"] = state
            elif (
                status == "healthy"
                and isinstance(previous, dict)
                and previous.get("status") in {"suspect", "contaminated"}
            ):
                writes["meta/state"] = state
                self._resolve_existing(previous.get("alert_id"), writes)
                alert = self._make_alert(
                    bag,
                    "contamination-recovered",
                    f"Bag {bag_id} was classified healthy. Staff review is recommended.",
                    "low",
                    "resolved",
                )
                alert["bag_id"] = bag_id
                self._queue_alert(alert, writes)
                bags.pop(bag_id, None)
                state["bag_alert_state"] = bags
                writes["meta/state"] = state
            self.database.update(writes)
        if alert:
            self._dispatch([alert])
            return [alert]
        return []

    def create_manual_alert(self, alert: dict[str, Any]) -> bool:
        """Atomically queue a manual alert and apply type/location/severity cooldown."""
        callback_alert = dict(alert)
        with self._lock:
            state = self._load_state()
            cooldowns = state["alert_cooldowns"]
            identity = "|".join(
                str(alert.get(field, "")) for field in ("type", "location", "level")
            )
            key = f"manual-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
            if not self._cooldown_ready(cooldowns.get(key)):
                return False
            callback_alert["timestamp"] = self._now_text()
            writes: dict[str, Any] = {"meta/state": state}
            self._queue_alert(callback_alert, writes)
            cooldowns[key] = callback_alert["timestamp"]
            state["alert_cooldowns"] = cooldowns
            writes["meta/state"] = state
            self.database.update(writes)
        self._dispatch([callback_alert])
        return True

    def check_once(self) -> list[dict[str, Any]]:
        """Raise a stale-sensor alert and escalate unresolved environmental alerts."""
        now = self.clock().astimezone(UTC)
        stale_after = self.settings.sensor_stale_minutes * 60
        escalated_after = self.settings.escalation_minutes * 60
        created: list[dict[str, Any]] = []
        writes: dict[str, Any] = {}
        with self._lock:
            state = self._load_state()
            last_sensor = _parse_time(state.get("last_sensor_ts")) or self._started_at
            offline = state.get("sensor_offline")
            if offline is None and (now - last_sensor).total_seconds() >= stale_after:
                sample = {"room": "Farm"}
                alert = self._make_alert(
                    sample,
                    "sensor-offline",
                    "No sensor readings have arrived recently.",
                    "high",
                    "open",
                )
                alert_id = self._queue_alert(alert, writes)
                state["sensor_offline"] = {
                    "alert_id": alert_id,
                    "raised_at": alert["timestamp"],
                }
                created.append(alert)

            active = state["alert_state"]
            for item in active.values():
                if not isinstance(item, dict) or item.get("escalated"):
                    continue
                raised = _parse_time(item.get("raised_at"))
                if raised is None or (now - raised).total_seconds() < escalated_after:
                    continue
                alert_id = item.get("alert_id")
                alert = self.database.get(f"alerts/{alert_id}") if alert_id else None
                if (
                    not isinstance(alert, dict)
                    or not alert
                    or alert.get("status") != "open"
                ):
                    item["escalated"] = True
                    continue
                alert.update(
                    {
                        "level": "high",
                        "escalated": True,
                        "escalated_at": self._now_text(),
                    }
                )
                writes[f"alerts/{alert_id}"] = alert
                item["level"] = "high"
                item["escalated"] = True
                created.append(alert)

            state["alert_state"] = active
            writes["meta/state"] = state
            if writes:
                self.database.update(writes)
        self._dispatch(created)
        return created

    def start_monitor(self, interval_seconds: float = 1.0) -> bool:
        """Start one daemon monitor for this DB instance; return false if already owned."""
        with _MONITOR_LOCK:
            owner = _MONITORS.get(self.database)
            if owner and owner.monitor_running:
                return False
            if self.monitor_running:
                return False
            _MONITORS[self.database] = self
            self._owns_monitor = True
            self._stop_event.clear()
            self._thread = Thread(
                target=self._monitor_loop,
                args=(interval_seconds,),
                name="mushroom-alert-monitor",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop_monitor(self, timeout: float = 5.0) -> None:
        """Stop and join the monitor thread without blocking process shutdown indefinitely."""
        self._stop_event.set()
        if self._thread and self._thread is not current_thread():
            self._thread.join(timeout=max(0.0, timeout))
        if self._owns_monitor:
            with _MONITOR_LOCK:
                if _MONITORS.get(self.database) is self:
                    _MONITORS.pop(self.database, None)
            self._owns_monitor = False

    def _monitor_loop(self, interval_seconds: float) -> None:
        """Run periodic checks until stop is requested; provider errors remain isolated."""
        while not self._stop_event.wait(max(0.05, interval_seconds)):
            try:
                self.check_once()
            except Exception as exc:  # noqa: BLE001 - monitor must survive a temporary store outage.
                LOGGER.error("Alert monitor check failed (%s)", type(exc).__name__)

    def _load_state(self) -> dict[str, Any]:
        """Load known state maps and repair missing/corrupt documents in memory."""
        raw = self.database.get("meta/state")
        state = dict(raw) if isinstance(raw, dict) else {}
        for name in ("alert_state", "alert_cooldowns", "bag_alert_state"):
            if not isinstance(state.get(name), dict):
                state[name] = {}
        if not isinstance(state.get("sensor_offline"), dict):
            state["sensor_offline"] = None
        return state

    def _queue_alert(self, alert: dict[str, Any], writes: dict[str, Any]) -> str:
        """Allocate a push key and stage an alert for the caller's atomic update."""
        alert_id = self.database.new_key("alerts")
        alert["id"] = alert_id
        writes[f"alerts/{alert_id}"] = alert
        return alert_id

    def _resolve_existing(self, alert_id: Any, writes: dict[str, Any]) -> None:
        """Stage a resolution update for an alert that still exists."""
        if not isinstance(alert_id, str) or not alert_id:
            return
        existing = self.database.get(f"alerts/{alert_id}")
        if isinstance(existing, dict) and existing:
            existing.update({"status": "resolved", "resolved_at": self._now_text()})
            writes[f"alerts/{alert_id}"] = existing

    def _cooldown_ready(self, last_value: Any) -> bool:
        """Return whether a type/room/severity key can raise another alert."""
        last = _parse_time(last_value)
        if last is None:
            return True
        elapsed = (self.clock().astimezone(UTC) - last).total_seconds()
        return elapsed >= self.settings.alert_cooldown_seconds

    def _make_alert(
        self, reading: dict[str, Any], kind: str, message: str, level: str, status: str
    ) -> dict[str, Any]:
        """Build a timestamped alert record without exposing sensor secrets."""
        return {
            "type": kind,
            "message": message,
            "location": reading["room"],
            "level": level,
            "status": status,
            "timestamp": self._now_text(),
            "notified": False,
        }

    def _now(self) -> datetime:
        """Read the injected UTC clock."""
        value = self.clock()
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    def _now_text(self) -> str:
        """Format the injected time as offset-aware UTC ISO-8601."""
        return self._now().isoformat(timespec="seconds")

    def _dispatch(self, alerts: list[dict[str, Any]]) -> None:
        """Submit notifications after database work, isolating notifier failures."""
        if not self.notify:
            return
        for alert in alerts:
            try:
                self.notify(alert)
            except Exception as exc:  # noqa: BLE001 - notification failure must not fail ingestion.
                LOGGER.error(
                    "Could not queue an alert notification (%s)", type(exc).__name__
                )


def _parse_time(value: Any) -> datetime | None:
    """Parse persisted timestamps with naive legacy values treated as UTC."""
    if not isinstance(value, str):
        return None
    try:
        text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(text)
        return (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    except ValueError:
        return None
