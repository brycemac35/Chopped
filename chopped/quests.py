"""
quests.py -- daily jobs and a light narrative arc on top of them, ported from
a Unity design doc (CHOPPED_QUEST_SYSTEM.md) that assumed NetworkBehaviours,
ScriptableObject quest assets and named NPCs (Paige, Tommy, the Fixer) this
game doesn't have. The shape survives -- 15 jobs, 3 rotating per day, story
points that move you through 3 acts -- but it's grounded in what Chopped
actually is:

- No "start quest" button. All 3 of today's jobs are tracked at once, in the
  background, off whatever you're already doing -- steal a Kei and you're
  automatically working "Hot Wire Special" if it's in today's three. This
  fits the game's fast, prompt-driven pace far better than a menu would, and
  it means nobody's staring at a quest board instead of playing.
- No AI racer, no second drop-off point, no mid-drive stripping from the
  passenger seat -- a few of the original 15 leaned on Unity mechanics that
  don't exist here. Each one's adapted to the closest thing Chopped actually
  does; see the comment on that job below for what changed and why.
- No NPC dialogue system. Story beats are toasts with a name on them
  ("PAIGE: ..."), the same way every other line in this game talks to you --
  see lines.py. That was true even in the original Unity doc's own scope
  (dialogue UI, voice acting and NPC models are all listed under "what's not
  included" there too).
- The crew shares one set of jobs, same as the shared wallet and shared
  heat: no per-player quest state to keep in sync.

This is a World mixin, no pygame. Job definitions are plain data so the
client can render names/briefs from QUESTS without anything riding the wire
except which 3 ids are live today, which are done, story points and the act.
"""

import math

from . import config as C
from . import vehicles as V
from .enums import T_BAD, T_INFO, T_MONEY, T_SAY, S_CASH

# ---------------------------------------------------------------------------
# The 15 jobs. Order is fixed -- it's how a job's index (not its string id)
# rides the wire (see protocol.QUEST_HDR). Never reorder this list; append
# only, or you'll rewrite everyone's in-flight save and in-progress jobs.
# ---------------------------------------------------------------------------
QUEST_ORDER = (
    "hotwire_special", "heat_run", "part_collector", "night_job", "engine_pull",
    "body_shop_wars", "the_repo", "clown_car_chaos", "corporate_contract", "catch_release",
    "perfect_steal", "black_market_deal", "the_escape", "family_business", "king_of_downtown",
)

# id -> (name, brief, difficulty, cash, rep, min_story_points, time_limit_s or None, coop_label)
QUESTS = {
    "hotwire_special": ("HOT WIRE SPECIAL", "STEAL A KEI HATCH. KEEP HEAT UNDER 40. DELIVER IT CLEAN.",
                        "EASY", 280, 1, 0, 240.0, False),
    "heat_run": ("HEAT RUN", "DELIVER ANY CAR. DON'T LET HEAT SIT OVER 60 FOR MORE THAN 20S.",
                 "EASY", 320, 1, 0, None, False),
    "part_collector": ("PART COLLECTOR", "STRIP 3 ONE-HANDED PARTS.",
                       "EASY", 300, 1, 0, None, False),
    "night_job": ("NIGHT JOB", "STEAL A CAR, STAY FREE FOR 90S, DELIVER IT UNCRASHED.",
                 "HARD", 500, 1, 0, None, False),
    "engine_pull": ("THE ENGINE PULL", "DELIVER A CAR WITH ITS ENGINE IN, WINCH IT OUT, BOLT IT ON YOUR OWN RIDE.",
                   "MEDIUM", 400, 2, 6, None, True),
    "body_shop_wars": ("BODY SHOP WARS", "TOMMY'S AFTER THE SAME CAR. STEAL AND DELIVER ONE INSIDE 5 MINUTES.",
                       "MEDIUM", 350, 2, 6, 300.0, False),
    "the_repo": ("THE REPO", "STEAL A CAR WHOSE OWNER'S WATCHING, AND DELIVER IT ANYWAY.",
                "MEDIUM", 280, 1, 0, None, False),
    "clown_car_chaos": ("CLOWN CAR CHAOS", "FIND A CLOWN CAR AND DELIVER IT. THE CLOWNS ARE NOT OPTIONAL.",
                       "MEDIUM", 200, 1, 0, None, False),
    "corporate_contract": ("THE CORPORATE CONTRACT", "DELIVER A CAR WITH 5+ STYLED PARTS. KEEP HEAT UNDER 30.",
                          "MEDIUM", 450, 2, 6, None, False),
    "catch_release": ("CATCH & RELEASE", "HOLD 70+ HEAT FOR 2 MINUTES WITHOUT GETTING BUSTED, THEN DELIVER.",
                      "HARD", 380, 2, 6, None, False),
    "perfect_steal": ("THE PERFECT STEAL", "STEAL AND DELIVER A CAR WITHOUT A SCRATCH ON IT.",
                      "HARD", 320, 1, 0, None, False),
    "black_market_deal": ("BLACK MARKET DEAL", "DELIVER TWO DIFFERENT 5+ STYLED-PART CARS WITHIN 5 MINUTES OF EACH OTHER.",
                          "HARD", 600, 2, 16, None, True),
    "the_escape": ("THE ESCAPE", "STEAL LOUD ON PURPOSE. STAY FREE 3 MINUTES OR REACH THE SHOP.",
                  "HARD", 400, 3, 16, None, False),
    "family_business": ("FAMILY BUSINESS", "DELIVER WITH A PASSENGER ABOARD, THEN HAVE THEM STRIP 2 PARTS.",
                        "MEDIUM", 350, 2, 6, None, True),
    "king_of_downtown": ("KING OF DOWNTOWN", "DELIVER 3 CARS BACK TO BACK, EACH WITHIN 2 MINUTES OF THE LAST.",
                        "HARD", 800, 4, 16, 480.0, True),
}

STYLED_THRESHOLD = 5           # (corporate_contract/black_market_deal) "tuned-tier" == this many styled parts
ACT_THRESHOLDS = (6, 16, 25)   # story points -> act II, act III, campaign-complete (ACT_NAMES below)
ACT_NAMES = ("STRUGGLING", "GROWING", "DOMINANCE")
ACT_BEATS = {
    2: ("PAIGE", "WORD'S GETTING AROUND TOWN. KEEP THIS UP AND WE WON'T BE STRUGGLING MUCH LONGER."),
    3: ("TOMMY", "...FINE. YOU WIN. JUST DON'T RUB IT IN."),
}

# (v0.12.1, Bryce: "there are no quest NPC's") what the people standing around say when you walk
# up and press E. mapgen.CityMap.story_npcs says where they stand; this is what comes out of them.
PAIGE_HELLO = {
    1: ("RIGHT. WE'RE BROKE AND THE LANDLORD'S CIRCLING. HERE'S TODAY'S WORK:",
        "ANOTHER DAY, ANOTHER RENT CHEQUE WE CAN'T COVER. JOBS:"),
    2: ("PEOPLE ARE STARTING TO KNOW OUR NAME. LET'S GIVE THEM A REASON:",
        "BUSINESS IS GOOD. DON'T GET COMFORTABLE. TODAY:"),
    3: ("DOWNTOWN'S OURS. MOSTLY. HERE'S HOW WE KEEP IT:",
        "TOMMY'S STILL SULKING. HERE'S TODAY'S LIST:"),
}
TOMMY_LINES = ("YOUR SHOP SMELLS LIKE BURNT CLUTCH, PAL.", "EVERY CAR YOU NICK IS ONE I DIDN'T. FOR NOW.",
               "NICE KEI. DID IT COME WITH A CRAYON?", "THIS LOT'S MINE TILL SOMEBODY PAYS FOR IT. SO: MINE.",
               "I'D RACE YOU BUT I DON'T RACE PEOPLE WHO PARK LIKE THAT.")
TOMMY_LOST = ("...YOU BOUGHT MY SPOT. I'M JUST STANDING HERE. IT'S A FREE COUNTRY.",
              "FINE. YOU WIN THIS ONE. I'M NOT CRYING, IT'S EXHAUST FUMES.")
TOMMY_RIVAL = "BODY SHOP WARS, EH? THAT CAR'S AS GOOD AS MINE. TICK TOCK."
KINGPIN_LINES = {
    1: ("COME BACK WHEN YOU'RE SOMEBODY. THIS LOT'S NOT FOR SMALL FRY.",
        "YOU'RE THE KEI PEOPLE? ADORABLE."),
    2: ("I HEAR THINGS ABOUT YOUR CREW. GOOD THINGS. MOSTLY LOUD THINGS.",
        "THIRTY GRAND AND THIS LOT'S YOURS. THE RPGS COME WITH IT."),
    3: ("DOWNTOWN'S YOURS NOW. DON'T FORGET WHO SOLD YOU THE ROCKETS.",
        "YOU'VE DONE WELL. I'M ONLY A LITTLE BIT TERRIFIED."),
}
FIXER_STOCKED = "THAT'S EVERY LOT IN TOWN, BOSS. NOTHING LEFT TO SELL YOU BUT ADVICE."
SHOP_TIER_SELLS = {1: "SHOTGUNS, BANANAS AND DONUTS", 2: "SMGS, RIFLES AND THE JOKE-SHOP STUFF",
                   3: "SNIPERS, GRENADE LAUNCHERS AND ROCKETS"}


def compass_word(dx, dy):
    """A rough direction for somebody giving you directions ("up north", "out east")."""
    a = math.degrees(math.atan2(dy, dx)) % 360          # screen y is down: 90 = south
    return ("EAST", "SOUTH-EAST", "SOUTH", "SOUTH-WEST", "WEST", "NORTH-WEST", "NORTH",
            "NORTH-EAST")[int((a + 22.5) // 45) % 8]


def wrap(text, width):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word) if line else word
    if line:
        lines.append(line)
    return lines


class Quests:
    def _init_quests(self):
        self.story_points = 0
        self.act = 1
        self.campaign_won = False
        self.today_quests = []          # up to 3 ids, this "day"
        self.quest_progress = {}        # id -> tracker dict, only for ids in today_quests
        self.quest_done_today = set()
        self.completed_ever = set()     # for stats/save; never cleared by a rotation or SHOP SEIZED
        self.talk_cd = {}               # (v0.12.1) story NPC key -> time they'll talk again
        self._rotate_quests()

    def _rotate_quests(self):
        """New day, new jobs. Picked from whatever your story points have unlocked; a job
        already done forever isn't excluded (Bryce may want the cash again), only masked
        as DONE TODAY until the next rotation."""
        pool = [q for q in QUEST_ORDER if QUESTS[q][5] <= self.story_points]
        self.today_quests = self.rng.sample(pool, min(3, len(pool)))
        self.quest_progress = {q: {} for q in self.today_quests}
        self.quest_done_today = set()
        if self.players:
            self.toast("TODAY'S JOBS: %s" % ", ".join(QUESTS[q][0] for q in self.today_quests), T_INFO)

    def _q(self, qid):
        return self.quest_progress.setdefault(qid, {})

    def _complete_quest(self, qid, bonus=0):
        if qid not in self.today_quests or qid in self.quest_done_today:
            return
        name, _, _, cash, rep, _, _, _ = QUESTS[qid]
        pay = cash + bonus
        self.quest_done_today.add(qid)
        self.completed_ever.add(qid)
        self.quest_progress[qid] = {}
        self._earn(pay)
        self.story_points += rep
        self.sfx(S_CASH, *self.map.garage_center)
        self.toast("JOB DONE: %s (+$%d, +%d REP)" % (name, pay, rep), T_MONEY)
        self._check_act_up()

    def _fail_quest(self, qid, reason=None):
        if qid not in self.today_quests or qid in self.quest_done_today:
            return
        self.quest_progress[qid] = {}
        if reason:
            self.toast("JOB BLOWN: %s -- %s" % (QUESTS[qid][0], reason), T_BAD)

    def _check_act_up(self):
        if self.story_points >= ACT_THRESHOLDS[0] and self.act < 2:
            self._act_up(2)
        if self.story_points >= ACT_THRESHOLDS[1] and self.act < 3:
            self._act_up(3)
        if self.story_points >= ACT_THRESHOLDS[2] and not self.campaign_won:
            self.campaign_won = True
            self.toast("THE CREW RUNS DOWNTOWN NOW. CREDITS ROLL (OR KEEP GOING -- NOBODY'S STOPPING YOU).",
                      T_MONEY)

    def _act_up(self, act):
        self.act = act
        beat = ACT_BEATS.get(act)
        if beat:
            self.toast("%s: %s" % beat, T_INFO)
        self.toast("ACT %s: %s" % (("I", "II", "III")[act - 1], ACT_NAMES[act - 1]), T_INFO)

    # ------------------------------------------------------------------ (v0.12.1) the people
    def _say(self, name, text):
        """A line of dialogue for the HUD's speech box (T_SAY): wrapped to what one toast
        event carries, the speaker's name on the first line only."""
        for i, line in enumerate(wrap(text, 56 - len(name))):
            self.toast(("%s: %s" % (name, line)) if i == 0 else "  " + line, T_SAY)

    def _talk_interaction(self, p, ax, ay):
        best, bd = None, C.TALK_RANGE
        for npc in self.map.story_npcs:
            d = math.hypot(npc[2] - ax, npc[3] - ay)
            if d < bd:
                best, bd = npc, d
        if best is None:
            return None
        key, name = best[0], best[1]
        return (("talk", key), "E: TALK TO %s" % name, 0, lambda: self._talk(p, key, name))

    def _talk(self, p, key, name):
        if self.time < self.talk_cd.get(key, 0.0):
            return
        self.talk_cd[key] = self.time + C.TALK_COOLDOWN
        pick = self.rng.choice
        if key == "paige":
            self._say(name, pick(PAIGE_HELLO[max(1, min(3, self.act))]))
            left = [q for q in self.today_quests if q not in self.quest_done_today]
            for qid in left:
                qn, brief, diff, cash, rep, _, tlim, coop = QUESTS[qid]
                extra = (" (CREW JOB)" if coop else "") + (" %d MIN LIMIT." % (tlim // 60) if tlim else "")
                self._say(name, "%s, $%d: %s%s" % (qn, cash, brief, extra))
            if not left:
                self._say(name, "THAT'S THE LOT FOR TODAY. GO STEAL SOMETHING FOR FUN.")
        elif key == "fixer":
            for i in range(1, len(self.shop_owned)):
                if self.shop_owned[i] or i - 1 >= len(self.map.fence_shops):
                    continue
                fs = self.map.fence_shops[i - 1]
                hx, hy = self.map.garage_center
                fx, fy = fs["center"]
                self._say(name, "THERE'S A LOT %dM %s OF HERE. $%s AND IT'S YOURS: %s, AND $%d A DAY RENT."
                          % (math.hypot(fx - hx, fy - hy), compass_word(fx - hx, fy - hy),
                             "{:,}".format(C.SHOP_PRICE[i]), SHOP_TIER_SELLS.get(fs["tier"], "MORE STOCK"),
                             C.SHOP_RENT[i]))
                break
            else:
                self._say(name, FIXER_STOCKED)
        elif key == "tommy":
            owned = any(self.shop_owned[i] for i in range(1, len(self.shop_owned))
                        if i - 1 < len(self.map.fence_shops) and self.map.fence_shops[i - 1]["tier"] == 1)
            if owned:
                self._say(name, pick(TOMMY_LOST))
            elif "body_shop_wars" in self.today_quests and "body_shop_wars" not in self.quest_done_today:
                self._say(name, TOMMY_RIVAL)
            else:
                self._say(name, pick(TOMMY_LINES))
        elif key == "kingpin":
            self._say(name, pick(KINGPIN_LINES[max(1, min(3, self.act))]))

    def _tuned_count(self, car):
        return sum(1 for part in car.parts.values() if part is not None and part.style > 0)

    # ------------------------------------------------------------------ tick
    def _quest_tick(self, dt):
        for qid in self.today_quests:
            if qid in self.quest_done_today:
                continue
            q = self._q(qid)
            if qid == "hotwire_special":
                if "car" in q:
                    q["t"] = q.get("t", 0.0) + dt
                    if self.heat >= 40.0 or q["t"] > QUESTS[qid][6]:
                        self._fail_quest(qid, "too hot or too slow" if self.heat >= 40 else "took too long")
            elif qid == "heat_run":
                # (no "car" to track -- any delivery counts, so this just watches the
                # clock continuously; a bad run cools back to 0 on its own, no permanent
                # fail, so the next delivery gets an honest shot at it)
                if self.heat > 60.0:
                    q["over_t"] = q.get("over_t", 0.0) + dt
                else:
                    q["over_t"] = 0.0
            elif qid == "night_job":
                if "car" in q and "evaded" not in q:
                    q["t"] = q.get("t", 0.0) + dt
                    if q["t"] >= 90.0:
                        q["evaded"] = True
            elif qid == "body_shop_wars":
                if "car" in q:
                    q["t"] = q.get("t", 0.0) + dt
                    if q["t"] > QUESTS[qid][6]:
                        self._fail_quest(qid, "TOMMY BEAT YOU TO IT")
            elif qid == "catch_release":
                if self.heat >= 70.0:
                    q["t"] = q.get("t", 0.0) + dt
                    if q["t"] >= 120.0:
                        q["earned"] = True
                else:
                    q["t"] = 0.0
            elif qid == "perfect_steal":
                if "car" in q:
                    car = self.cars.get(q["car"])
                    if car is None or car.damage > 0:
                        self._fail_quest(qid, "not so perfect")
            elif qid == "the_escape":
                if "car" in q:
                    q["t"] = q.get("t", 0.0) + dt
                    if q["t"] >= 180.0:
                        self._complete_quest(qid)
            elif qid == "black_market_deal":
                if "first_t" in q and self.time - q["first_t"] > 300.0:
                    q.clear()

    # ------------------------------------------------------------------ hooks
    def _quest_on_steal(self, p, car):
        for qid in self.today_quests:
            if qid in self.quest_done_today:
                continue
            q = self._q(qid)
            if qid == "hotwire_special" and "car" not in q and car.model == V.KEI:
                q["car"], q["t"] = car.id, 0.0
            elif qid == "night_job" and "car" not in q:
                q["car"], q["t"] = car.id, 0.0
            elif qid == "body_shop_wars" and "car" not in q:
                q["car"], q["t"] = car.id, 0.0
            elif qid == "the_repo" and "car" not in q and car.special == "owner":
                q["car"] = car.id
            elif qid == "clown_car_chaos" and "car" not in q and car.special == "clown":
                q["car"] = car.id
            elif qid == "perfect_steal" and "car" not in q:
                q["car"] = car.id
            elif qid == "the_escape" and "car" not in q and car.alarm:
                # (adapted) "guaranteed max heat alarm" -> any loud theft: a smashed window,
                # a failed wire cut, a carjacking or a stolen cop car, all of which set the
                # alarm. A clean wire-cut deliberately does NOT arm this job -- the whole
                # point is picking the noisy way in on purpose.
                q["car"], q["t"] = car.id, 0.0

    def _quest_on_deliver(self, car, driver_pid, passenger_pid, heat_at_delivery):
        tuned = self._tuned_count(car)
        for qid in self.today_quests:
            if qid in self.quest_done_today:
                continue
            q = self._q(qid)
            if qid == "hotwire_special" and q.get("car") == car.id:
                if self.heat < 40.0 and car.damage == 0:
                    self._complete_quest(qid)
                else:
                    self._fail_quest(qid, "crashed it")
            elif qid == "heat_run" and q.get("over_t", 0.0) <= 20.0:
                self._complete_quest(qid)
            elif qid == "night_job" and q.get("car") == car.id:
                if q.get("evaded") and car.damage == 0:
                    self._complete_quest(qid)
                else:
                    # (v0.12.1) it used to say "not clean enough" for both, and the playtest
                    # read "too quick" as "too dirty". Say which. (Progress resets; the next
                    # car you steal gets a fresh go.)
                    self._fail_quest(qid, "CRASHED IT. NEXT CAR" if car.damage > 0 else
                                     "HOME BEFORE 90S. NEXT CAR")
            elif qid == "engine_pull":
                if car.parts.get("Engine") is not None:
                    q["delivered_with_engine"] = car.id
            elif qid == "body_shop_wars" and q.get("car") == car.id:
                self._complete_quest(qid)
            elif qid == "the_repo" and q.get("car") == car.id:
                self._complete_quest(qid)
            elif qid == "clown_car_chaos" and q.get("car") == car.id:
                self._complete_quest(qid)
            elif qid == "corporate_contract" and tuned >= STYLED_THRESHOLD and heat_at_delivery < 30.0:
                self._complete_quest(qid)
            elif qid == "catch_release" and q.get("earned"):
                self._complete_quest(qid)
            elif qid == "perfect_steal" and q.get("car") == car.id:
                if car.damage == 0:
                    self._complete_quest(qid)
            elif qid == "black_market_deal" and tuned >= STYLED_THRESHOLD:
                if "first_car" not in q:
                    q["first_car"], q["first_t"] = car.id, self.time
                elif car.id != q["first_car"] and self.time - q["first_t"] <= 300.0:
                    self._complete_quest(qid, bonus=0)
            elif qid == "the_escape" and q.get("car") == car.id:
                self._complete_quest(qid)
            elif qid == "family_business" and passenger_pid is not None and car.damage == 0:
                q["passenger"], q["count"] = passenger_pid, 0
            elif qid == "king_of_downtown":
                self._king_of_downtown_deliver(q, car.id)

    def _king_of_downtown_deliver(self, q, car_id):
        if car_id == q.get("last_car"):
            return
        now = self.time
        if q.get("n", 0) == 0 or now - q.get("last_t", 0.0) > 120.0 or now - q.get("start_t", 0.0) > 480.0:
            q["n"], q["start_t"] = 1, now
        else:
            q["n"] = q.get("n", 0) + 1
        q["last_t"], q["last_car"] = now, car_id
        if q["n"] >= 3:
            self._complete_quest("king_of_downtown")

    def _quest_on_strip(self, p, part):
        for qid in self.today_quests:
            if qid in self.quest_done_today:
                continue
            q = self._q(qid)
            if qid == "part_collector" and part.bulk == 1:
                # (adapted) the original doc paid a bonus per part beyond 3, which assumed
                # a separate "bring them to the shop" turn-in step this version doesn't have
                # (there's no quest-start/turn-in menu here -- see the module docstring) --
                # without it there's no way to hold more than 3 before the job completes, so
                # the bonus dropped out along with the step it was paying you to take.
                q["count"] = q.get("count", 0) + 1
                if q["count"] >= 3:
                    self._complete_quest(qid)
            elif qid == "family_business" and q.get("passenger") == p.id:
                q["count"] = q.get("count", 0) + 1
                if q["count"] >= 2:
                    self._complete_quest(qid)

    def _quest_on_dolly_engine(self, p, car):
        q = self._q("engine_pull")
        if "engine_pull" in self.today_quests and "engine_pull" not in self.quest_done_today:
            if q.get("delivered_with_engine") == car.id:
                q["engine_stripped"] = True

    def _quest_on_install(self, p, car, slot):
        if slot != "Engine":
            return
        q = self._q("engine_pull")
        if "engine_pull" in self.today_quests and "engine_pull" not in self.quest_done_today:
            if q.get("engine_stripped"):
                self._complete_quest("engine_pull")

    def _quest_on_arrest(self, p):
        for qid in self.today_quests:
            if qid in self.quest_done_today:
                continue
            q = self._q(qid)
            if qid == "night_job" and "car" in q:
                self._fail_quest(qid, "busted")
            elif qid == "catch_release" and q.get("t", 0.0) > 0:
                self._fail_quest(qid, "busted")
            elif qid == "the_escape" and "car" in q:
                self.cash = max(0, self.cash - 100)
                self._fail_quest(qid, "busted, -$100")
