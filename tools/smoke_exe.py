"""
smoke_exe.py -- proves a BUILT executable works, not just the source.

    python tools/smoke_exe.py dist/Chopped.exe      (Windows)
    python tools/smoke_exe.py dist/Chopped          (Linux)

1. Solo selftest: the exe boots headless, hosts, and a bot plays for 300 frames.
2. Two copies of the exe: one hosts, the other joins it over 127.0.0.1 UDP,
   both bot-driven for ~15 s. The host must see 2 players.

The exe is windowed (no console), so everything goes through --log files,
which are printed at the end whatever happens.
"""

import os
import re
import socket
import subprocess
import sys
import time


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return "(no log written)"


def run(exe, args, log):
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    return subprocess.Popen([exe] + args + ["--log", log], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    exe = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                          os.path.join("dist", "Chopped.exe" if os.name == "nt" else "Chopped"))
    if not os.path.exists(exe):
        print("!! no executable at %s" % exe)
        return 2
    out = os.path.join(os.path.dirname(exe), "smoke-logs")
    os.makedirs(out, exist_ok=True)
    print("== smoke testing %s (%.1f MB)" % (exe, os.path.getsize(exe) / 1e6))
    ok = True

    # 1) solo selftest
    solo = os.path.join(out, "solo.log")
    t0 = time.time()
    p = run(exe, ["--selftest", "--frames", "300"], solo)
    rc = p.wait(timeout=180)
    text = read(solo)
    print("-- solo selftest: exit %d in %.1fs\n%s" % (rc, time.time() - t0, text.strip()))
    if rc != 0 or "SELFTEST OK" not in text:
        ok = False

    # 2) host + client, two separate processes of the same exe
    port = free_udp_port()
    hlog, clog = os.path.join(out, "host.log"), os.path.join(out, "client.log")
    host = run(exe, ["--selftest", "--seconds", "24", "--port", str(port), "--name", "HOSTY"], hlog)
    time.sleep(3.0)          # onefile exes unpack themselves first; give the host a head start
    client = run(exe, ["--selftest", "--seconds", "13", "--join", "127.0.0.1:%d" % port,
                       "--name", "CLIENTY"], clog)
    crc = client.wait(timeout=180)
    hrc = host.wait(timeout=180)
    htext, ctext = read(hlog), read(clog)
    print("-- host: exit %d\n%s" % (hrc, htext.strip()))
    print("-- client: exit %d\n%s" % (crc, ctext.strip()))
    m = re.search(r"players_seen=(\d+)", htext)
    if hrc != 0 or crc != 0 or "SELFTEST OK" not in htext or "SELFTEST OK" not in ctext:
        ok = False
    if not (m and int(m.group(1)) >= 2):
        print("!! host never saw the client join")
        ok = False
    print("== SMOKE %s" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
