"""
Chopped -- a co-op car-theft chop-shop game. Entry point.

    python main.py                       # menu
    python main.py --host                # host straight away
    python main.py --join 1.2.3.4:27015  # join straight away
    python main.py --server              # headless dedicated host (no window)
    python main.py --selftest            # boot headless, bot plays ~5 s, exit 0 if OK
"""

import argparse
import os
import sys
import time


def _fix_stdio(log_path=None):
    # A PyInstaller --windowed exe has no console, so sys.stdout is None and
    # the first print() would take the whole game down. Point them somewhere
    # harmless -- or at --log FILE, which is how CI (and you, when something
    # breaks on a friend's PC) gets to read what the exe had to say.
    if log_path:
        try:
            f = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
            sys.stdout = sys.stderr = f
            return
        except OSError:
            pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def _windows_tweaks():
    # Without this, Windows "helpfully" bitmap-stretches the window on 125%/150%
    # display scaling and our crisp pixels turn to porridge. SDL reads hints
    # from same-named environment variables; everywhere else it's ignored.
    os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="Chopped", description="Co-op car theft. Crime pays (rent).")
    ap.add_argument("--host", action="store_true", help="host a game immediately")
    ap.add_argument("--join", metavar="IP[:PORT]", help="join a game immediately")
    ap.add_argument("--name", help="your crook name (max 12 chars)")
    ap.add_argument("--port", type=int, default=None, help="UDP port to host on (default 27015)")
    ap.add_argument("--server", action="store_true", help="run a headless dedicated host")
    ap.add_argument("--selftest", action="store_true", help="headless boot + bot play, exit 0 if OK")
    ap.add_argument("--frames", type=int, default=None, help="selftest: frames to run")
    ap.add_argument("--seconds", type=float, default=None, help="selftest/server: seconds to run")
    ap.add_argument("--mute", action="store_true", help="no audio")
    ap.add_argument("--no-upnp", dest="no_upnp", action="store_true", help="don't try UPnP")
    ap.add_argument("--log", metavar="FILE", help="write all output (and crash tracebacks) to FILE")
    return ap.parse_args(argv)


def run_server(args):
    from chopped import config as C
    from chopped.net import Server, get_lan_ip
    from chopped.upnp import UPnP
    port = args.port or C.DEFAULT_PORT
    srv = Server(port=port)
    up = None if args.no_upnp else UPnP(srv.port).start()
    print("Chopped dedicated host on UDP %d  (LAN %s:%d). Ctrl+C to stop." % (srv.port, get_lan_ip(), srv.port))
    srv.start()
    t0 = time.time()
    last = 0.0
    try:
        while True:
            time.sleep(0.25)
            now = time.time() - t0
            if args.seconds and now > args.seconds:
                break
            if now - last > 10:
                last = now
                w = srv.world
                print("[%5.0fs] players=%d cash=$%d heat=%d %s" % (
                    now, srv.player_count, w.cash, w.heat, up.status if up else ""))
    except KeyboardInterrupt:
        pass
    srv.stop()
    if up:
        up.close()
    return 0


def main(argv=None):
    _fix_stdio()
    args = parse_args(argv)
    if args.log:
        _fix_stdio(args.log)
    _windows_tweaks()
    if args.server:
        return run_server(args)
    if args.selftest:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from chopped.game import App, run_selftest
    if args.selftest:
        return run_selftest(args)
    try:
        App(args).run()
    except Exception:
        import traceback
        traceback.print_exc()        # lands in --log FILE if given; the exe also shows a dialog
        sys.stderr.flush()
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
