"""Frozen clock thresholds for a Linux host and its owned execution container."""

import json
import queue
import select
import subprocess
import sys
import threading
import time


class ClockGate:
    def __init__(self):
        self.previous = None
        self.offsets = []
        self.samples = 0

    def sample(self, wall, mono):
        self.samples += 1
        error = None
        if self.previous is not None:
            dw, dm = wall - self.previous[0], mono - self.previous[1]
            if dw < -1_000_000:
                error = "WALL_ROLLBACK"
            elif dm <= 0:
                error = "MONOTONIC_NOT_ADVANCING"
            elif abs(dw - dm) > 100_000_000:
                error = "CLOCK_RESIDUAL"
        self.previous = (wall, mono)
        return error

    def offset(self, before, after, guest):
        if after < before:
            return "WALL_ROLLBACK"
        if after - before < 100_000_000:
            self.offsets.append(guest - (before + after) // 2)
            if max(self.offsets) - min(self.offsets) >= 100_000_000:
                return "HOST_GUEST_OFFSET"
        return None


def worker():
    """Sample at 100Hz; answer bracketed host pings without loading project code."""
    while True:
        wall, mono = time.time_ns(), time.monotonic_ns()
        print(json.dumps({"kind": "sample", "wall": wall, "mono": mono}), flush=True)
        if select.select([sys.stdin], [], [], 0.01)[0]:
            line = sys.stdin.readline()
            if not line:
                return
            ping = json.loads(line)
            print(
                json.dumps({"kind": "pong", "id": ping["id"], "wall": time.time_ns()}),
                flush=True,
            )


class Monitor:
    """Owns only sampler threads and one docker exec process. Never reads secrets."""

    def __init__(self, container, script, output):
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.host, self.guest = ClockGate(), ClockGate()
        self.started = time.monotonic()
        self.last_guest = self.started
        self.last_host = self.started
        self.next_ping = self.started
        self.pings = {}
        self.output = output
        self.process = subprocess.Popen(
            ["docker", "exec", "-i", container, "python", script, "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.threads = [
            threading.Thread(target=self._host),
            threading.Thread(target=self._guest),
        ]
        for thread in self.threads:
            thread.start()

    def _host(self):
        try:
            with (self.output / "host-clock.jsonl").open("x") as stream:
                while not self.stop.is_set():
                    wall, mono = time.time_ns(), time.monotonic_ns()
                    error = self.host.sample(wall, mono)
                    stream.write(
                        json.dumps({"wall": wall, "mono": mono, "error": error}) + "\n"
                    )
                    self.last_host = time.monotonic()
                    if error:
                        self.events.put(error)
                    self.stop.wait(0.01)
        except Exception:  # noqa: BLE001 - Any host sampler failure must reject clock admission.
            self.events.put("HOST_SAMPLER_ERROR")
        finally:
            if not self.stop.is_set():
                self.events.put("HOST_SAMPLER_EXITED")

    def _guest(self):
        try:
            with (self.output / "guest-clock.jsonl").open("x") as stream:
                for line in self.process.stdout:
                    now = time.time_ns()
                    row = json.loads(line)
                    self.last_guest = time.monotonic()
                    error = None
                    if row["kind"] == "sample":
                        error = self.guest.sample(row["wall"], row["mono"])
                    elif row["kind"] == "pong":
                        error = self.guest.offset(
                            self.pings.pop(row["id"]), now, row["wall"]
                        )
                    else:
                        raise ValueError("UNKNOWN_CLOCK_FRAME")
                    stream.write(
                        json.dumps(row | {"host_received": now, "error": error}) + "\n"
                    )
                    if error:
                        self.events.put(error)
        except Exception:  # noqa: BLE001 - Any guest sampler failure must reject clock admission.
            self.events.put("SAMPLER_ERROR")
        finally:
            if not self.stop.is_set():
                self.events.put("SAMPLER_EXITED")

    def check(self):
        now = time.monotonic()
        if now - self.last_guest > 3 or now - self.last_host > 3:
            raise RuntimeError("CLOCK_SAMPLER_STALLED")
        if any(not thread.is_alive() for thread in self.threads):
            raise RuntimeError("CLOCK_SAMPLER_THREAD_EXITED")
        if now >= self.next_ping:
            if len(self.pings) > 3:
                raise RuntimeError("CLOCK_PONG_MISSING")
            stamp = time.time_ns()
            self.pings[stamp] = stamp
            self.process.stdin.write(json.dumps({"id": stamp}) + "\n")
            self.process.stdin.flush()
            self.next_ping = now + 1
        if not self.events.empty():
            raise RuntimeError(self.events.get())

    def admit(self):
        end = self.started + 60
        while time.monotonic() < end:
            self.check()
            time.sleep(0.01)
        if (
            min(self.host.samples, self.guest.samples) < 5000
            or len(self.guest.offsets) < 30
        ):
            raise RuntimeError("INSUFFICIENT_CLOCK_OBSERVATIONS")

    def close(self):
        self.stop.set()
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=5)
        if any(thread.is_alive() for thread in self.threads):
            raise RuntimeError("CLOCK_THREAD_NOT_CLOSED")
        if not self.events.empty():
            raise RuntimeError("CLOCK_FATAL_EVENT_AT_CLOSE")


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker()
