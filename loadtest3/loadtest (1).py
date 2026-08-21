#!/usr/bin/env python3

import argparse
import multiprocessing as mp
import os
import time
import math
import random


# ============================================================
# LAB CONFIGURATION
# ============================================================

# CHANGE 1: scale worker count to the box instead of hardcoding it.
# A fixed "2 CPU workers" only produces oversubscription on a 2-vCPU VM.
# Tying it to os.cpu_count() means the lab produces the same teaching
# effect (load average > core count) on any machine a student runs it on.
CPU_COUNT = os.cpu_count() or 2
OVERSUB_FACTOR = 2.5  # total CPU-bound workers = CPU_COUNT * this

# Maximum TOTAL disk space used by all I/O workers
MAX_TOTAL_DISK_GB = 5

# Two I/O workers -> 2.5 GiB each (kept fixed; disk contention doesn't
# need to scale with core count the way CPU contention does)
IO_WORKERS = 2

MAX_TOTAL_DISK_BYTES = MAX_TOTAL_DISK_GB * 1024 * 1024 * 1024
PER_WORKER_DISK_BYTES = MAX_TOTAL_DISK_BYTES // IO_WORKERS

BLOCK_SIZE = 1024 * 1024  # 1 MB

# CHANGE 7: configurable I/O target directory instead of hardcoded /tmp.
# Needed for filesystem/mount-point experiments (M-OS-03) — e.g. comparing
# contention behavior when writes land on the root filesystem vs. a
# dedicated data mount, or a mount with different options (noatime, etc).
DEFAULT_DISK_DIR = "/tmp"

# CHANGE 8: optional Prometheus metrics export. prometheus_client is not a
# stdlib module — import it lazily and degrade gracefully (print a warning,
# continue without metrics) if it isn't installed, rather than making it a
# hard dependency for students who just want the plain OS-contention lab.
try:
    from prometheus_client import start_http_server, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ============================================================
# CHANGE 3: shared timestamp helper so every worker's print lines up
# cleanly against a second terminal running iostat/vmstat/pidstat.
# ============================================================

def ts():
    return time.strftime("%H:%M:%S")


def log(pid, name, message):
    print(f"[{ts()}] [{pid}] {name}: {message}")


# ============================================================
# CPU WORKER (floating point)
# ============================================================

def cpu_worker(name, duration):

    pid = os.getpid()
    log(pid, name, "CPU intensive process (floating point)")

    end_time = time.time() + duration

    x = 0.0001

    while time.time() < end_time:

        x = math.sin(x) * math.cos(x) + math.sqrt(abs(x) + 1)

    log(pid, name, "finished")


# ============================================================
# CPU WORKER 2 (integer)
# ============================================================

def cpu_worker_2(name, duration):

    pid = os.getpid()
    log(pid, name, "CPU intensive process (integer)")

    end_time = time.time() + duration

    value = 1234567

    while time.time() < end_time:

        value = (value * 1103515245 + 12345) & 0x7FFFFFFF

    log(pid, name, "finished")


# ============================================================
# MEMORY WORKER
# ============================================================

def memory_worker(name, size_mb, duration):

    pid = os.getpid()
    log(pid, name, f"allocating {size_mb} MB")

    data = bytearray(size_mb * 1024 * 1024)

    # Touch every page so memory is actually committed
    page_size = 4096

    for i in range(0, len(data), page_size):
        data[i] = 1

    log(pid, name, f"holding {size_mb} MB")

    time.sleep(duration)

    del data

    log(pid, name, "released memory")


# ============================================================
# DISK I/O WORKER
# ============================================================

def io_worker(name, duration, max_bytes, use_fsync=True, disk_dir=DEFAULT_DISK_DIR):

    pid = os.getpid()

    filename = os.path.join(disk_dir, f"{name}_{pid}.dat")

    mode_label = "fsync-per-block (synchronous)" if use_fsync else "buffered (no fsync — dirty page buildup mode)"

    log(
        pid, name,
        f"disk I/O process (maximum file size = {max_bytes / (1024**3):.2f} GiB, mode: {mode_label})"
    )

    block = os.urandom(BLOCK_SIZE)

    end_time = time.time() + duration

    bytes_written = 0

    # CHANGE 5 (--no-fsync): when use_fsync is False, open with normal buffering
    # instead of buffering=0/unbuffered raw I/O, and skip os.fsync() after each
    # write. This lets writes land in the kernel's page cache and accumulate as
    # dirty pages (visible in `sar -r`'s kbdirty column, or /proc/meminfo's
    # `Dirty:` line) instead of being forced to disk immediately — this is what
    # M-OS-02 Step 1 needs to demonstrate vm.dirty_ratio/dirty_background_ratio
    # behavior. With use_fsync=True (the default) the original synchronous,
    # every-write-durable behavior from M-OS-01 is unchanged.
    open_mode_kwargs = {"buffering": 0} if use_fsync else {}

    try:

        with open(filename, "w+b", **open_mode_kwargs) as f:

            while time.time() < end_time:

                # CHANGE 4: narrow try/except around the actual I/O calls.
                # If /tmp fills up or a permission/disk error occurs mid-run,
                # the original script let the raw traceback kill this worker
                # silently while the other 9 processes kept running with no
                # visible signal that one had died. Now we log clearly and
                # exit this worker on its own rather than crashing unlabeled.
                try:

                    if bytes_written < max_bytes:

                        remaining = max_bytes - bytes_written

                        write_size = min(BLOCK_SIZE, remaining)

                        f.write(block[:write_size])

                        if use_fsync:

                            f.flush()
                            os.fsync(f.fileno())

                        bytes_written += write_size

                    else:

                        f.seek(0)

                        bytes_written = 0

                        if use_fsync:
                            f.flush()

                        log(
                            pid, name,
                            f"{max_bytes / (1024**3):.2f} GiB limit reached - "
                            f"reusing existing file"
                        )

                except OSError as e:

                    log(pid, name, f"I/O ERROR: {e} — stopping this worker")
                    break

            # Final flush so buffered (no-fsync) mode doesn't leave the last
            # batch of writes silently un-flushed to the OS layer at exit.
            if not use_fsync:
                f.flush()

    finally:

        if os.path.exists(filename):
            os.remove(filename)

    log(pid, name, "finished")


# ============================================================
# MIXED CPU + MEMORY WORKER
# ============================================================

def mixed_worker(name, duration):

    pid = os.getpid()
    log(pid, name, "mixed workload")

    data = bytearray(50 * 1024 * 1024)

    end_time = time.time() + duration

    while time.time() < end_time:

        # CPU activity
        for _ in range(100000):
            math.sqrt(random.random() + 1)

        # Memory activity
        for i in range(0, len(data), 4096 * 100):
            data[i] = (data[i] + 1) % 255

        time.sleep(0.1)

    del data

    log(pid, name, "finished")


# ============================================================
# IDLE WORKER
# ============================================================

def idle_worker(name, duration):

    pid = os.getpid()
    log(pid, name, "mostly idle process")

    time.sleep(duration)

    log(pid, name, "finished")


# ============================================================
# MAIN
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description="PostgreSQL DBA OS Performance Lab — synthetic mixed workload"
    )

    # CHANGE 2: duration is now a CLI arg instead of a hardcoded constant.
    # Makes it painless to run a 30-second smoke test while building a
    # module instead of editing the file every time.
    parser.add_argument(
        "--duration", type=int, default=300,
        help="How long to run the workload, in seconds (default: 300)"
    )

    parser.add_argument(
        "--oversub", type=float, default=OVERSUB_FACTOR,
        help=f"CPU-bound worker oversubscription factor (default: {OVERSUB_FACTOR})"
    )

    # CHANGE 6: explicit per-category worker count overrides. --oversub alone
    # can only shrink the CPU-bound category — memory/io/mixed/idle workers
    # were previously always present regardless of --oversub, which meant
    # there was no way to build a genuinely "memory-only" scenario. Setting
    # any of these to 0 removes that category entirely. Leave unset (None)
    # to keep the original fixed defaults (3 memory, 2 io, 2 mixed, 1 idle).
    parser.add_argument(
        "--cpu-workers", type=int, default=None,
        help="Explicit CPU-bound worker count, overrides --oversub entirely. 0 disables CPU workers."
    )
    parser.add_argument(
        "--memory-workers", type=int, default=None,
        help="Number of memory workers to run (cycles through 100/200/300MB sizes). Default: 3. 0 disables."
    )
    parser.add_argument(
        "--io-workers", type=int, default=None,
        help="Number of disk I/O workers, sharing the fixed 5 GiB total cap. Default: 2. 0 disables."
    )
    parser.add_argument(
        "--mixed-workers", type=int, default=None,
        help="Number of mixed CPU+memory workers. Default: 2. 0 disables."
    )
    parser.add_argument(
        "--idle-workers", type=int, default=None,
        help="Number of idle workers. Default: 1. 0 disables."
    )

    # CHANGE 5: --no-fsync switches the I/O workers from synchronous
    # (fsync-per-block, durable-on-write) to buffered writes that accumulate
    # as kernel dirty pages instead of hitting disk immediately. Use this to
    # demonstrate vm.dirty_ratio / vm.dirty_background_ratio behavior — watch
    # `Dirty:` in /proc/meminfo or sar -r's kbdirty column climb, then compare
    # against tuned dirty ratio sysctls (see M-OS-02, Step 1-2).
    parser.add_argument(
        "--no-fsync", action="store_true",
        help=(
            "Disable fsync() in the I/O workers so writes accumulate as "
            "kernel dirty pages instead of being forced to disk immediately. "
            "Use this to demonstrate vm.dirty_ratio behavior (see M-OS-02)."
        )
    )

    # CHANGE 7: configurable disk target directory for filesystem/mount
    # experiments (M-OS-03) — e.g. --disk-dir /u01/perf_lab to point I/O
    # workers at a dedicated data mount instead of /tmp.
    parser.add_argument(
        "--disk-dir", type=str, default=DEFAULT_DISK_DIR,
        help=f"Directory the I/O workers write into (default: {DEFAULT_DISK_DIR}). "
             f"Use this to compare contention behavior across filesystems/mounts."
    )

    # CHANGE 8: expose worker counts and duration as Prometheus gauges so
    # Grafana/Prometheus dashboards can show what the experiment IS, next to
    # what it DID (see M-OS-03 Grafana section). Requires `pip install
    # prometheus_client`; script runs normally without metrics if absent.
    parser.add_argument(
        "--metrics-port", type=int, default=None,
        help="If set, expose loadtest_* Prometheus gauges on this port "
             "(requires the prometheus_client package). Omit to disable."
    )

    return parser.parse_args()


def main():

    args = parse_args()
    duration = args.duration

    # CHANGE 1 (cont.): compute CPU-bound worker count from core count,
    # unless explicitly overridden by --cpu-workers.
    if args.cpu_workers is not None:
        cpu_worker_count = max(0, args.cpu_workers)
    else:
        cpu_worker_count = max(2, round(CPU_COUNT * args.oversub))

    # CHANGE 6 (cont.): resolve each category's worker count — explicit
    # override if given, else the original fixed default.
    memory_worker_count = args.memory_workers if args.memory_workers is not None else 3
    io_worker_count = args.io_workers if args.io_workers is not None else IO_WORKERS
    mixed_worker_count = args.mixed_workers if args.mixed_workers is not None else 2
    idle_worker_count = args.idle_workers if args.idle_workers is not None else 1

    # Recompute per-worker disk cap if the io worker count was overridden,
    # so the 5 GiB total cap still holds regardless of how many io workers run.
    if io_worker_count > 0:
        per_io_worker_bytes = MAX_TOTAL_DISK_BYTES // io_worker_count
    else:
        per_io_worker_bytes = 0

    memory_sizes_mb = (100, 200, 300)  # cycled through if memory_worker_count > 3

    # CHANGE 7 (cont.): fail early and clearly if the requested disk_dir
    # doesn't exist or isn't writable, rather than letting every io_worker
    # hit the same OSError independently and print IO_WORKER_N errors N times.
    if io_worker_count > 0:
        if not os.path.isdir(args.disk_dir):
            print(f"ERROR: --disk-dir '{args.disk_dir}' does not exist or is not a directory.")
            return
        if not os.access(args.disk_dir, os.W_OK):
            print(f"ERROR: --disk-dir '{args.disk_dir}' is not writable by this user.")
            return

    # CHANGE 8 (cont.): start the Prometheus metrics server if requested.
    metrics_gauges = None
    if args.metrics_port is not None:
        if not PROMETHEUS_AVAILABLE:
            print(
                "WARNING: --metrics-port was set but prometheus_client is not "
                "installed. Run 'pip install prometheus_client' to enable metrics. "
                "Continuing without metrics."
            )
        else:
            start_http_server(args.metrics_port)
            metrics_gauges = {
                "cpu_workers": Gauge("loadtest_cpu_workers", "Configured CPU-bound worker count"),
                "memory_workers": Gauge("loadtest_memory_workers", "Configured memory worker count"),
                "io_workers": Gauge("loadtest_io_workers", "Configured disk I/O worker count"),
                "mixed_workers": Gauge("loadtest_mixed_workers", "Configured mixed worker count"),
                "idle_workers": Gauge("loadtest_idle_workers", "Configured idle worker count"),
                "duration_seconds": Gauge("loadtest_duration_seconds", "Configured run duration"),
                "no_fsync": Gauge("loadtest_no_fsync", "1 if I/O workers are running without fsync, else 0"),
                "running": Gauge("loadtest_running", "1 while the workload is active, 0 otherwise"),
            }
            metrics_gauges["cpu_workers"].set(cpu_worker_count)
            metrics_gauges["memory_workers"].set(memory_worker_count)
            metrics_gauges["io_workers"].set(io_worker_count)
            metrics_gauges["mixed_workers"].set(mixed_worker_count)
            metrics_gauges["idle_workers"].set(idle_worker_count)
            metrics_gauges["duration_seconds"].set(duration)
            metrics_gauges["no_fsync"].set(1 if args.no_fsync else 0)
            metrics_gauges["running"].set(1)
            print(f"Prometheus metrics    : http://localhost:{args.metrics_port}/metrics")

    print("=" * 60)
    print("POSTGRESQL DBA OS PERFORMANCE LAB")
    print("=" * 60)

    print(f"Duration              : {duration} seconds")
    print(f"Detected CPU cores    : {CPU_COUNT}")
    if args.cpu_workers is not None:
        print(f"CPU workers           : {cpu_worker_count} (explicit override)")
    else:
        print(f"Oversubscription      : {args.oversub}x -> {cpu_worker_count} CPU-bound workers")
    print(f"Memory workers        : {memory_worker_count}")
    print(f"Mixed workers         : {mixed_worker_count}")
    print(f"Idle workers          : {idle_worker_count}")
    print(f"Maximum disk usage    : {MAX_TOTAL_DISK_GB} GiB TOTAL")
    print(f"I/O workers           : {io_worker_count}")
    if io_worker_count > 0:
        print(f"I/O target directory  : {args.disk_dir}")
        print(
            f"Maximum per I/O file  : "
            f"{per_io_worker_bytes / (1024**3):.2f} GiB"
        )
        print(
            f"I/O mode              : "
            f"{'BUFFERED, no fsync (dirty page buildup mode)' if args.no_fsync else 'fsync-per-block (synchronous, default)'}"
        )

    print("=" * 60)

    processes = []

    # --------------------------------------------------------
    # CPU — scaled to CPU_COUNT * oversub (or explicit --cpu-workers),
    # alternating worker types
    # --------------------------------------------------------

    for i in range(cpu_worker_count):

        target = cpu_worker if i % 2 == 0 else cpu_worker_2
        label = "CPU_FLOAT" if i % 2 == 0 else "CPU_INT"

        processes.append(
            mp.Process(target=target, args=(f"{label}_{i}", duration))
        )

    # --------------------------------------------------------
    # MEMORY
    # --------------------------------------------------------

    for i in range(memory_worker_count):

        size_mb = memory_sizes_mb[i % len(memory_sizes_mb)]

        processes.append(
            mp.Process(
                target=memory_worker,
                args=(f"MEMORY_{size_mb}MB_{i}", size_mb, duration)
            )
        )

    # --------------------------------------------------------
    # DISK I/O
    # --------------------------------------------------------

    for i in range(1, io_worker_count + 1):

        processes.append(
            mp.Process(
                target=io_worker,
                args=(f"IO_WORKER_{i}", duration, per_io_worker_bytes, not args.no_fsync, args.disk_dir)
            )
        )

    # --------------------------------------------------------
    # MIXED
    # --------------------------------------------------------

    for i in range(1, mixed_worker_count + 1):

        processes.append(
            mp.Process(target=mixed_worker, args=(f"MIXED_{i}", duration))
        )

    # --------------------------------------------------------
    # IDLE
    # --------------------------------------------------------

    for i in range(1, idle_worker_count + 1):

        processes.append(mp.Process(target=idle_worker, args=(f"IDLE_{i}", duration)))

    print()

    if not processes:
        print("No workers configured (all categories set to 0) — nothing to run.")
        if metrics_gauges is not None:
            metrics_gauges["running"].set(0)
        return

    print(f"Starting {len(processes)} workload processes...")
    print("-" * 60)

    for p in processes:

        p.start()

        print(f"[{ts()}] Started PID: {p.pid:<8} Process: {p.name}")

    print("-" * 60)

    print("All processes started.")
    print()
    print("Monitor from another terminal:")
    print("  top")
    print("  vmstat 1")
    print("  iostat -xz 1")
    print("  pidstat -urd 1")
    print("  free -h")
    print(f"  df -h {args.disk_dir}")
    print()
    print("Press Ctrl+C to stop the lab.")

    try:

        for p in processes:
            p.join()

        if metrics_gauges is not None:
            metrics_gauges["running"].set(0)

    except KeyboardInterrupt:

        print(f"\n[{ts()}] Stopping all processes...")

        for p in processes:

            if p.is_alive():
                p.terminate()

        for p in processes:
            p.join()

        if metrics_gauges is not None:
            metrics_gauges["running"].set(0)

        print(f"[{ts()}] All processes stopped.")


if __name__ == "__main__":
    main()
