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

ROAD, SIDEWALK, BUILDING, GRASS, TREE, WALL, GARAGE, LOT, PRECINCT = range(9)
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
        self.ramps = []         # (v0.9) (x, y, heading) stunt ramps
        self.parks = []
        self.lamps = []         # (x, y) metres, decorative
        self.cameras = []       # (x, y) metres
        self.parking = []       # (x, y, angle) metres
        self.cop_spawns = []    # (x, y, angle)
        self.sidewalk_tiles = []
        self.static_rects = []  # solid rectangles that aren't tiles (benches), metres (x, y, w, h)
        self.precinct_outer = self.precinct_rect = self.gate = None
        self.jail_spawns, self.guard_posts = [], []
        self.cells, self.cell_doors, self.cell_bars = [], [], []
        self.fence_shops = []    # (v0.12) shops 2-4: {"tier", "center", "sign", "market"}, buyable

        # ---- choose block types --------------------------------------------
        shop = (C.BLOCKS // 2, C.BLOCKS // 2)
        cells = [(i, j) for i in range(C.BLOCKS) for j in range(C.BLOCKS) if (i, j) != shop]
        # keep the shop's immediate neighbours as normal buildings so the
        # plaza reads as "downtown", then sprinkle parks/lots elsewhere
        far = [c for c in cells if abs(c[0] - shop[0]) + abs(c[1] - shop[1]) > 1]
        rng.shuffle(far)
        parks = set(far[:C.PARK_BLOCKS])
        lots = set(far[C.PARK_BLOCKS:C.PARK_BLOCKS + C.LOT_BLOCKS])
        # v0.8: the precinct. Far enough from the shop that breaking out means a run home.
        rest = [c for c in far[C.PARK_BLOCKS + C.LOT_BLOCKS:]
                if abs(c[0] - shop[0]) + abs(c[1] - shop[1]) >= C.PRECINCT_MIN_BLOCKS]
        precinct = rest[0] if rest else None
        # (v0.12) shops 2-4, purchasable: tier N sits at fences[N-1]. Skip -- and cheerfully
        # ship a 1-shop city -- if a tiny custom BLOCKS/PARK_BLOCKS/LOT_BLOCKS combo (a test
        # fixture, say) leaves nothing free after the precinct's had its pick.
        fences = rest[1:1 + (len(C.SHOP_MARKET) - 1)]

        for i in range(C.BLOCKS):
            for j in range(C.BLOCKS):
                ox = C.ROAD_TILES + i * C.PITCH
                oy = C.ROAD_TILES + j * C.PITCH
                if (i, j) == shop:
                    self._make_shop(ox, oy)
                elif (i, j) == precinct:
                    self._make_precinct(ox, oy)
                elif (i, j) in fences:
                    self._make_fence(rng, ox, oy, fences.index((i, j)) + 1)
                elif (i, j) in parks:
                    self._make_park(rng, ox, oy)
                elif (i, j) in lots:
                    self._make_lot(rng, ox, oy)
                else:
                    self._make_buildings(rng, ox, oy)

        self._make_parking(rng, shop)
        self._make_ramps()
        self._make_cameras(rng)
        self._make_lamps()
        self._make_cop_spawns()

        self.solid = bytearray(1 if t in SOLID_TYPES else 0 for t in self.tiles)
        self.opaque = bytearray(1 if t in OPAQUE_TYPES else 0 for t in self.tiles)
        self._merge_solids()
        self.grass_tiles = []         # (v0.7: where the garden gnomes live)
        for ty in range(n):
            for tx in range(n):
                t = self.tiles[ty * n + tx]
                if t == SIDEWALK:
                    self.sidewalk_tiles.append((tx, ty))
                elif t == GRASS:
                    self.grass_tiles.append((tx, ty))
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
        # (v0.10, Bryce: "back alleys between big building sizes") a foot-only service alley
        # straight through the middle, splitting the block into two building masses either
        # side of it: a shortcut for peds, and somewhere to duck a witness's sightline. It's
        # ALLEY_W tiles (4 m) wide -- too narrow for any car, so traffic never goes near it.
        aw = C.ALLEY_W
        a0 = (inner - aw) // 2
        horiz = rng.random() < 0.5           # which way the alley (and the split) runs
        if horiz:
            self._fill(x0, y0 + a0, inner, aw, SIDEWALK)
            halves = ((y0, a0), (y0 + a0 + aw, inner - a0 - aw))
        else:
            self._fill(x0 + a0, y0, aw, inner, SIDEWALK)
            halves = ((x0, a0), (x0 + a0 + aw, inner - a0 - aw))
        for pos, size in halves:
            if size <= 0:
                continue
            style = rng.randrange(6)
            if horiz:
                self.buildings.append((x0, pos, inner, size, style))
            else:
                self.buildings.append((pos, y0, size, inner, style))

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

    def _make_ramps(self):
        """(v0.9) A stunt ramp across the middle of every car park, pointing east or west.
        (Its own random stream, so adding ramps didn't move a single building.)"""
        import random
        r = random.Random(self.seed * 7 + 1)
        T = C.TILE_M
        self.ramps = []
        for (tx, ty, tw, th) in self.lots[:C.RAMP_COUNT]:
            ang = 0.0 if r.random() < 0.5 else math.pi
            self.ramps.append(((tx + tw / 2) * T, (ty + th / 2) * T, ang))

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

    def _make_fence(self, rng, ox, oy, tier):
        """(v0.12, Bryce: "make multiple garages, make them available for purchase") shops
        2-4: an open lot, not a real building -- buy it and its market crates come alive. No
        bays, no roller door of its own: a second full garage/door/raycaster system was a lot
        of plumbing for "the black market has more stuff now" (see CLAUDE.md's build notes).
        It deliberately isn't added to self.lots, so it gets no parking-space paint, no stunt
        ramp, and no civilian cars trying to park on top of the crates.

        Calls _make_buildings first purely to burn the same rng draws an ordinary block would
        have, then throws away the tiles and buildings it made -- the same trick _make_ramps
        uses its own rng stream for. Without this, buying (or not buying) fence shops would
        reshuffle every random choice made for the rest of the city after them: traffic
        models, camera spots, ped spawns, all of it, for a feature that's supposed to just
        add some crates in an empty lot. A real, reproducible case of this cost us a very
        rare pre-existing traffic pathing edge case surfacing in testing before this fix."""
        nb = len(self.buildings)
        self._make_buildings(rng, ox, oy)
        del self.buildings[nb:]
        inner = C.BLOCK_TILES - 2
        self._fill(ox + 1, oy + 1, inner, inner, LOT)
        cx = (ox + 1 + inner / 2) * C.TILE_M
        cy = (oy + 1 + inner / 2) * C.TILE_M
        items = C.SHOP_MARKET[tier]
        x0 = cx - 1.75 * (len(items) - 1) / 2
        market = [(x0 + k * 1.75, cy + 2.0, item) for k, item in enumerate(items)]
        self.fence_shops.append({"tier": tier, "center": (cx, cy), "sign": (cx, cy - 3.0), "market": market})

    def _make_shop(self, ox, oy):
        """The chop shop: open-fronted garage facing south onto the road."""
        b = C.BLOCK_TILES
        self._fill(ox, oy, b, b, GARAGE)
        for t in range(b - 1):            # side walls stop one short: that row is the apron
            self._set(ox, oy + t, WALL)
            self._set(ox + b - 1, oy + t, WALL)
        for t in range(b):
            self._set(ox + t, oy, WALL)
        # (v0.10, Bryce: "make the garage door smaller, make a walking entrance and a bay for
        # each player that joins") the front used to be one 28 m roller door; now it's five
        # small ones (config.DOOR_COLS picks which of these 7 tile-columns are doors: 0 =
        # walking door, 1-4 = each player's own bay). The two columns left over are ordinary
        # wall -- a pier between the first pair of bays and the second -- so shutting every
        # door really does seal the place, with no gap between doors for a witness to see
        # through, because there's no floor there to stand on.
        for k in range(b - 2):
            if k not in C.DOOR_COLS:
                self._set(ox + 1 + k, oy + b - 1, WALL)
        T = C.TILE_M
        # delivery zone = the covered floor (not the apron). 28 x 28 m of crime.
        self.garage_rect = ((ox + 1) * T, (oy + 1) * T, (b - 2) * T, (b - 2) * T)
        self.garage_tiles = (ox, oy, b, b)
        gx, gy, gw, gh = self.garage_rect
        # one bay per player slot, nose pointing out that bay's own door (config.DOOR_COLS[1:])
        self.bays = [(gx + (col + 0.5) * T, gy + gh - 6.0, math.pi / 2) for col in C.DOOR_COLS[1:]]
        self.bay = self.bays[0]           # (kept as a single tuple: plenty of code still wants "the" bay)
        # the hand dolly's parking spot, tucked in the north-east corner
        self.dolly_spot = (gx + gw - 2.5, gy + 4.5)
        # the black market: a row of crates along the west wall. Don't ask where they came from.
        # (v0.12, Bryce: "shop 1 has just basic parts and the pistol") the rest of the old
        # lineup -- the shotgun, the silly stuff -- moved out to the fence shops (SHOP_MARKET
        # tiers 1-3); buy those and their crates carry it instead.
        self.market = [(gx + 1.0, gy + 3.2 + k * 1.75, item)
                       for k, item in enumerate(C.SHOP_MARKET[0])]
        self.sell_bench = (gx + 5.0, gy, 6.0, 1.6)
        self.tune_bench = (gx + gw - 11.0, gy, 6.0, 1.6)
        self.static_rects.append(self.sell_bench)
        self.static_rects.append(self.tune_bench)
        cx = gx + gw / 2
        self.player_spawns = [(cx - 2, gy + 5), (cx + 2, gy + 5), (cx - 2, gy + 8), (cx + 2, gy + 8)]
        self.garage_center = (gx + gw / 2, gy + gh / 2)

    def _make_precinct(self, ox, oy):
        """The police station (v0.8): a walled lockup in the middle of a block,
        one gated doorway onto the south street, a front desk for bail. The
        cells are an open-plan concept. It's very modern."""
        b = C.BLOCK_TILES
        self._ring(ox, oy)
        x0, y0, inner = ox + 1, oy + 1, b - 2
        self._fill(x0, y0, inner, inner, WALL)
        self._fill(x0 + 1, y0 + 1, inner - 2, inner - 2, PRECINCT)
        T = C.TILE_M
        door = x0 + inner // 2
        self._set(door, y0 + inner - 1, PRECINCT)                    # the doorway (the gate goes here)
        self.precinct_tiles = (x0, y0, inner, inner)
        self.precinct_rect = ((x0 + 1) * T, (y0 + 1) * T, (inner - 2) * T, (inner - 2) * T)   # the lockup
        self.precinct_outer = (x0 * T, y0 * T, inner * T, inner * T)                          # walls and all
        self.gate = ((door + 0.5) * T, (y0 + inner - 0.5) * T, math.pi / 2)                   # spans x
        px, py, pw, ph = self.precinct_rect
        # v0.9 (Bryce: "have a small jail cell you need to break out of first"): two barred
        # cells in the north corners. Bars are thin solid rects (they don't block sight -- it's
        # a cell, not a cupboard); each cell has a door in its south bars (a TRAP_CELL: punch
        # it off its hinges, or pick it).
        cs, dw, t = C.CELL_SIZE, C.CELL_DOOR_W, C.CELL_BAR_T
        self.cells, self.cell_doors, self.cell_bars = [], [], []
        for k, cx0 in enumerate((px, px + pw - cs)):
            self.cells.append((cx0, py, cs, cs))
            wy = py + cs                                      # the south bars
            dx0 = cx0 + (cs - dw) / 2
            bars = [(cx0, wy - t / 2, dx0 - cx0, t), (dx0 + dw, wy - t / 2, cx0 + cs - dx0 - dw, t)]
            side = cx0 + cs if k == 0 else cx0                # the bars facing the hall
            bars.append((side - t / 2, py, t, cs + t / 2))
            self.cell_bars.extend(bars)
            self.static_rects.extend(bars)
            self.cell_doors.append((dx0 + dw / 2, wy, math.pi / 2))
        self.jail_spawns = [(x + cs / 2 + off, py + cs / 2 - 0.5)
                            for off in (-1.2, 1.2) for (x, _y, _w, _h) in self.cells]
        self.guard_posts = [(px + 3.0, py + ph - 4.5), (px + pw - 3.0, py + ph - 4.5), (px + pw / 2, py + ph / 2 + 1.5)]
        self.bail_desk = (px + pw / 2 - 2.25, py + 1.0, 4.5, 1.4)     # in the hall, between the cells
        self.static_rects.append(self.bail_desk)
        self.precinct_exit = ((door + 0.5) * T, (y0 + inner + 0.6) * T)   # the street, just outside

    def cell_at(self, x, y):
        """Index of the jail cell (x, y) is inside, or -1."""
        for k, (cx, cy, cw, ch) in enumerate(self.cells):
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                return k
        return -1

    def in_precinct(self, x, y):
        """Inside the police station's walls, lockup side of the gate. (The doorway is
        split down the middle by the gate: north of it you're a prisoner, south of it
        you're a member of the public with a lock pick.)"""
        if self.precinct_outer is None:
            return False
        ox, oy, ow, oh = self.precinct_outer
        return ox <= x <= ox + ow and oy <= y < self.gate[1]

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
