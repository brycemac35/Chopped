"""Runs the ACTUAL game loop (pygame window on the dummy driver, renderer,
HUD, audio, networking) in two processes: a host and a client that joins it
over 127.0.0.1. Both are driven by the selftest bot for ~20 s and must exit 0.
"""

import os
import re
import socket
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_udp_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestGameLoop(unittest.TestCase):
    def test_host_and_client_run_20s_headless(self):
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        port = free_udp_port()
        main = os.path.join(ROOT, "main.py")
        host = subprocess.Popen([sys.executable, main, "--selftest", "--seconds", "23", "--port", str(port),
                                 "--name", "HOSTY"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(1.5)
        client = subprocess.Popen([sys.executable, main, "--selftest", "--seconds", "19",
                                   "--join", "127.0.0.1:%d" % port, "--name", "CLIENTY"], cwd=ROOT, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        c_out, _ = client.communicate(timeout=60)
        h_out, _ = host.communicate(timeout=60)
        print("\n[host]  ", h_out.strip().splitlines()[-1])
        print("[client]", c_out.strip().splitlines()[-1])
        self.assertEqual(client.returncode, 0, c_out)
        self.assertEqual(host.returncode, 0, h_out)
        self.assertIn("SELFTEST OK", h_out)
        self.assertIn("SELFTEST OK", c_out)
        # the host really saw a second player join
        m = re.search(r"players_seen=(\d+)", h_out)
        self.assertTrue(m and int(m.group(1)) >= 2, h_out)
        # and neither side dropped way below frame rate
        for out in (h_out, c_out):
            fps = float(re.search(r"fps=([\d.]+)", out).group(1))
            self.assertGreater(fps, 30, out)


if __name__ == "__main__":
    unittest.main()
