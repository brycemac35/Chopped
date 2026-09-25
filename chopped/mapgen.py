"""
mapgen.py -- a procedural city: a grid of blocks, roads between them, and a
chop shop smack in the middle because zoning laws are for people with
legitimate businesses.

The generator is fully deterministic from a seed, so the host just tells
clients "seed 1234" and everyone builds the identical city locally. Cheaper
than sending 12,000 tiles over UDP and about 12,000 times less annoying.
"""

import math
import random
from collections import deque

from . import config as C

ROAD, SIDEWALK, BUILDING, GRASS, TREE, WALL, GARAGE, LOT = range(8)
SOLID_TYPES = (BUILDING, TREE, WALL)
OPAQUE_TYPES = (BUILDING, TREE, WALL)   # trees block sight: parks are hiding spots


class CityMap:
    def __init__(self, seed):
        self.seed = seed
        rng = random.Random(seed)
        n = C.MAP_TILES
        self.n = n
        self.tiles = bytearray([ROAD]) * (n * n)
        self.buildings = []     # (tx, ty, tw, th, style)
        self.lots = []          # (tx, ty, tw, th)
        self.parks = []
        self.lamps = []         # (x, y) metres, decorative
        self.cameras = []       # (x, y) metres
        self.parking = []       # (x, y, angle) metres
        self.cop_spawns = []    # (x, y, angle)
        self.sidewalk_tiles = []
        self.static_rects = []  # solid rectangles that aren't tiles (benches), metres (x, y, w, h)

        # ---- choose block types --------------------------------------------
        shop = (C.BLOCKS // 2, C.BLOCKS // 2)
        cells = [(i, j) for i in range(C.BLOCKS) for j in range(C.BLOCKS) if (i, j) != shop]
        # keep the shop's immediate neighbours as normal buildings so the
        # plaza reads as "downtown", then sprinkle parks/lots elsewhere
        far = [c for c in cells if abs(c[0] - shop[0]) + abs(c[1] - shop[1]) > 1]
        rng.shuffle(far)
        parks = set(far[:C.PARK_BLOCKS])
        lots = set(far[C.PARK_BLOCKS:C.PARK_BLOCKS + C.LOT_BLOCKS])

        for i in range(C.BLOCKS):
            for j in range(C.BLOCKS):
                ox = C.ROAD_TILES + i * C.PITCH
                oy = C.ROAD_TILES + j * C.PITCH
                if (i, j) == shop:
                    self._make_shop(ox, oy)
                elif (i, j) in parks:
                    self._make_park(rng, ox, oy)
                elif (i, j) in lots:
                    self._make_lot(rng, ox, oy)
                else:
                    self._make_buildings(rng, ox, oy)

        self._make_parking(rng, shop)
        self._make_cameras(rng)
        self._make_lamps()
        self._make_cop_spawns()

        self.solid = bytearray(1 if t in SOLID_TYPES else 0 for t in self.tiles)
        self.opaque = bytearray(1 if t in OPAQUE_TYPES else 0 for t in self.tiles)
        self._merge_solids()
        for ty in range(n):
            for tx in range(n):
                if self.tiles[ty * n + tx] == SIDEWALK:
                    self.sidewalk_tiles.append((tx, ty))
        self._flow_cache = {}

    # ------------------------------------------------------------------ blocks
    def _set(self, tx, ty, t):
        if 0 <= tx < self.n and 0 <= ty < self.n:
            self.tiles[ty * self.n + tx] = t

    def _fill(self, tx, ty, tw, th, t):
        for y in range(ty, ty + th):
            for x in range(tx, tx + tw):
                self._set(x, y, t)

    def _ring(self, ox, oy):
        self._fill(ox, oy, C.BLOCK_TILES, C.BLOCK_TILES, SIDEWALK)

    def _make_buildings(self, rng, ox, oy):
        self._ring(ox, oy)
        inner = C.BLOCK_TILES - 2
        x0, y0 = ox + 1, oy + 1
        self._fill(x0, y0, inner, inner, BUILDING)
        # split the block into 1-3 buildings so roofs aren't one giant slab
        parts = rng.choice((1, 2, 2, 3))
        horiz = rng.random() < 0.5
        cuts = sorted(rng.sample(range(2, inner - 1), parts - 1)) if parts > 1 else []
        edges = [0] + cuts + [inner]
        for a, b in zip(edges, edges[1:]):
            style = rng.randrange(6)
            if horiz:
                self.buildings.append((x0 + a, y0, b - a, inner, style))
            else:
                self.buildings.append((x0, y0 + a, inner, b - a, style))

    def _make_park(self, rng, ox, oy):
        self._ring(ox, oy)
        inner = C.BLOCK_TILES - 2
        self._fill(ox + 1, oy + 1, inner, inner, GRASS)
        self.parks.append((ox + 1, oy + 1, inner, inner))
        # trees on a loose lattice so a car can still weave through (badly)
        for y in range(inner):
            for x in range(inner):
                if (x % 2 == 0 and y % 2 == 0) and rng.random() < 0.55:
                    self._set(ox + 1 + x, oy + 1 + y, TREE)

    def _make_lot(self, rng, ox, oy):
        self._ring(ox, oy)
        inner = C.BLOCK_TILES - 2
        self._fill(ox + 1, oy + 1, inner, inner, LOT)
        self.lots.append((ox + 1, oy + 1, inner, inner))
        # two rows of nose-in bays along the north and south edges of the lot
        bx = (ox + 1) * C.TILE_M
        by = (oy + 1) * C.TILE_M
        span = inner * C.TILE_M
        for k in range(6):
            x = bx + 3.0 + k * 4.4
            if x > bx + span - 3.0:
                break
            self.parking.append((x, by + 3.0, math.pi / 2))
            self.parking.append((x, by + span - 3.0, -math.pi / 2))

    def _make_shop(self, ox, oy):
        """The chop shop: open-fronted garage facing south onto the road."""
        b = C.BLOCK_TILES
        self._fill(ox, oy, b, b, GARAGE)
        for t in range(b - 1):            # side walls stop one short: that row is the apron
            self._set(ox, oy + t, WALL)
            self._set(ox + b - 1, oy + t, WALL)
        for t in range(b):
            self._set(ox + t, oy, WALL)
        T = C.TILE_M
        # delivery zone = the covered floor (not the apron). 28 x 28 m of crime.
        self.garage_rect = ((ox + 1) * T, (oy + 1) * T, (b - 2) * T, (b - 2) * T)
        self.garage_tiles = (ox, oy, b, b)
        gx, gy, gw, gh = self.garage_rect
        # personal car bay on the west side, nose pointing out the door
        self.bay = (gx + 3.4, gy + gh - 6.0, math.pi / 2)
        # the hand dolly's parking spot, tucked in the north-east corner
        self.dolly_spot = (gx + gw - 2.5, gy + 4.5)
        # the black market: a row of crates along the west wall. Don't ask where they came from.
        self.market = [(gx + 1.0, gy + 5.0 + k * 1.9, item)
                       for k, item in enumerate(("pistol", "shotgun", "ammo", "spikes", "roadblock"))]
        self.sell_bench = (gx + 5.0, gy, 6.0, 1.6)
        self.tune_bench = (gx + gw - 11.0, gy, 6.0, 1.6)
        self.static_rects.append(self.sell_bench)
        self.static_rects.append(self.tune_bench)
        cx = gx + gw / 2
        self.player_spawns = [(cx - 2, gy + 5), (cx + 2, gy + 5), (cx - 2, gy + 8), (cx + 2, gy + 8)]
        self.garage_center = (gx + gw / 2, gy + gh / 2)

    def _make_parking(self, rng, shop):
        T = C.TILE_M
        sx0 = (C.ROAD_TILES + shop[0] * C.PITCH) * T
        sy_road = (C.ROAD_TILES + shop[1] * C.PITCH + C.BLOCK_TILES) * T
        for band in range(C.BLOCKS + 1):
            r0 = band * C.PITCH * T              # road band start (metres)
            for blk in range(C.BLOCKS):
                s0 = (C.ROAD_TILES + blk * C.PITCH) * T
                for off in (9.0, 27.0):
                    # horizontal roads: north curb faces west, south curb faces east
                    x = s0 + off
                    # keep the shop driveway clear
                    # (1.5 m from the kerb: tucked in tight so moving traffic fits past)
                    if not (abs(r0 - sy_road) < 1 and sx0 - 6 < x < sx0 + 42):
                        self.parking.append((x, r0 + 1.5, math.pi))
                        self.parking.append((x, r0 + 3 * T - 1.5, 0.0))
                    y = s0 + off
                    # vertical roads: west curb faces south, east curb faces north
                    self.parking.append((r0 + 1.5, y, math.pi / 2))
                    self.parking.append((r0 + 3 * T - 1.5, y, -math.pi / 2))

    def _make_cameras(self, rng):
        T = C.TILE_M
        spots = []
        for i in range(1, C.BLOCKS):
            for j in range(1, C.BLOCKS):
                cx = (i * C.PITCH + 1.5) * T
                cy = (j * C.PITCH + 1.5) * T
                for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    x, y = cx + dx * 8.2, cy + dy * 8.2
                    if self.tile_at(x, y) == SIDEWALK:
                        spots.append((x, y))
                        break
        rng.shuffle(spots)
        self.cameras = spots[:C.CAMERA_COUNT]

    def _make_lamps(self):
        T = C.TILE_M
        n = self.n
        for ty in range(n):
            for tx in range(n):
                if self.tiles[ty * n + tx] != SIDEWALK:
                    continue
                # lamps on the road-facing edge, every 3rd tile
                if (tx + ty) % 3:
                    continue
                for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    if self.tile(tx + dx, ty + dy) == ROAD:
                        self.lamps.append(((tx + 0.5 + dx * 0.35) * T, (ty + 0.5 + dy * 0.35) * T))
                        break

    def _make_cop_spawns(self):
        m = C.MAP_M
        mid = 1.5 * C.TILE_M
        k = 8.0
        while k < m - 8:
            self.cop_spawns.append((k, mid, math.pi / 2))
            self.cop_spawns.append((k, m - mid, -math.pi / 2))
            self.cop_spawns.append((mid, k, 0.0))
            self.cop_spawns.append((m - mid, k, math.pi))
            k += 12.0

    def _merge_solids(self):
        """Greedy-mesh solid tiles into as few rectangles as possible. Cars
        are boxes, and a box sliding along a wall built from 4 m tiles snags on
        every seam between them ("ghost edges"). One building = one rectangle
        = one smooth wall to scrape your doors off."""
        n = self.n
        T = C.TILE_M
        solid = self.solid
        owner = [-1] * (n * n)
        rects = []
        for ty in range(n):
            for tx in range(n):
                i = ty * n + tx
                if not solid[i] or owner[i] >= 0:
                    continue
                w = 1
                while tx + w < n and solid[i + w] and owner[i + w] < 0:
                    w += 1
                h = 1
                while ty + h < n and all(solid[(ty + h) * n + tx + k] and owner[(ty + h) * n + tx + k] < 0
                                         for k in range(w)):
                    h += 1
                rid = len(rects)
                rects.append((tx * T, ty * T, w * T, h * T))
                for yy in range(ty, ty + h):
                    row = yy * n
                    for xx in range(tx, tx + w):
                        owner[row + xx] = rid
        self.solid_rects = rects
        self.rect_owner = owner
        # the edge of the world: four fat walls just outside the map
        m, k = n * T, 40.0
        self.edge_rects = [(-k, -k, m + 2 * k, k), (-k, m, m + 2 * k, k), (-k, 0.0, k, m), (m, 0.0, k, m)]

    # ------------------------------------------------------------------ roads (for traffic)
    @staticmethod
    def road_centre(k):
        """Centre line (metres) of the k-th road band, k = 0..BLOCKS."""
        return (k * C.PITCH + C.ROAD_TILES / 2.0) * C.TILE_M

    def node_pos(self, i, j):
        return self.road_centre(i), self.road_centre(j)

    @staticmethod
    def node_ok(i, j):
        return 0 <= i <= C.BLOCKS and 0 <= j <= C.BLOCKS

    # ------------------------------------------------------------------ queries
    def tile(self, tx, ty):
        if 0 <= tx < self.n and 0 <= ty < self.n:
            return self.tiles[ty * self.n + tx]
        return WALL

    def tile_at(self, x, y):
        return self.tile(int(x // C.TILE_M), int(y // C.TILE_M))

    def solid_tile(self, tx, ty):
        if 0 <= tx < self.n and 0 <= ty < self.n:
            return self.solid[ty * self.n + tx]
        return 1

    def solid_at(self, x, y):
        return self.solid_tile(int(x // C.TILE_M), int(y // C.TILE_M))

    def in_garage(self, x, y):
        gx, gy, gw, gh = self.garage_rect
        return gx <= x <= gx + gw and gy <= y <= gy + gh

    def los(self, x0, y0, x1, y1):
        """Line of sight: march along the line in ~1 m steps looking for opaque
        tiles. Crude, fast, and nobody has ever noticed the difference."""
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        steps = int(d) + 1
        sx, sy = dx / steps, dy / steps
        x, y = x0, y0
        n = self.n
        T = C.TILE_M
        op = self.opaque
        for _ in range(steps):
            x += sx
            y += sy
            tx, ty = int(x // T), int(y // T)
            if 0 <= tx < n and 0 <= ty < n:
                if op[ty * n + tx]:
                    return False
            else:
                return False
        return True

    def ray_clear(self, x, y, ang, length, step=1.0):
        """Distance until a solid tile along a ray (for cop whiskers)."""
        ca, sa = math.cos(ang), math.sin(ang)
        d = step
        while d <= length:
            if self.solid_at(x + ca * d, y + sa * d):
                return d
            d += step
        return length

    def solid_rects_near(self, x, y, r, out):
        """Collect solid AABBs (metres, merged -- see _merge_solids) that
        overlap the square around a circle. Appends to `out` to avoid
        allocating a new list in the hot loop."""
        T = C.TILE_M
        n = self.n
        tx0, tx1 = int((x - r) // T), int((x + r) // T)
        ty0, ty1 = int((y - r) // T), int((y + r) // T)
        owner = self.rect_owner
        seen = ()
        for ty in range(max(0, ty0), min(n - 1, ty1) + 1):
            row = ty * n
            for tx in range(max(0, tx0), min(n - 1, tx1) + 1):
                rid = owner[row + tx]
                if rid >= 0 and rid not in seen:
                    seen += (rid,)
                    out.append(self.solid_rects[rid])
        if tx0 < 0 or ty0 < 0 or tx1 >= n or ty1 >= n:
            for rect in self.edge_rects:
                rx, ry, rw, rh = rect
                if x + r > rx and x - r < rx + rw and y + r > ry and y - r < ry + rh:
                    out.append(rect)
        for rect in self.static_rects:
            rx, ry, rw, rh = rect
            if x + r > rx and x - r < rx + rw and y + r > ry and y - r < ry + rh:
                out.append(rect)
        return out

    def flow_field(self, tx, ty):
        """BFS distance field over drivable tiles from (tx, ty). Cops roll
        downhill on it so they go round buildings instead of through them.
        Cached per target tile; the sim clears the cache every so often."""
        key = (tx, ty)
        f = self._flow_cache.get(key)
        if f is not None:
            return f
        n = self.n
        dist = [-1] * (n * n)
        if 0 <= tx < n and 0 <= ty < n:
            start = ty * n + tx
            dist[start] = 0
            q = deque([start])
            solid = self.solid
            while q:
                i = q.popleft()
                d = dist[i] + 1
                x = i % n
                if x > 0 and dist[i - 1] < 0 and not solid[i - 1]:
                    dist[i - 1] = d; q.append(i - 1)
                if x < n - 1 and dist[i + 1] < 0 and not solid[i + 1]:
                    dist[i + 1] = d; q.append(i + 1)
                if i >= n and dist[i - n] < 0 and not solid[i - n]:
                    dist[i - n] = d; q.append(i - n)
                if i < n * n - n and dist[i + n] < 0 and not solid[i + n]:
                    dist[i + n] = d; q.append(i + n)
        if len(self._flow_cache) > 8:
            self._flow_cache.clear()
        self._flow_cache[key] = dist
        return dist

    def clear_flow_cache(self):
        self._flow_cache.clear()
