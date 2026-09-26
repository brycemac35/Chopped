"""
story.py -- (v0.13) the main story. Bryce: "can you instate the story quests as a separate
persistent quest that updates when you finish it. still have the REP guard rails to progress.
but i need story quests and dialogue (written)."

So: ten chapters, one at a time, always on screen (under the radar, above the daily jobs).
Each one is handed to you by somebody -- Paige, the Fixer, Tommy or the Kingpin -- and you
start it by walking up to them and pressing E, which plays that chapter's opening scene.
Finish the objective and the closing scene plays wherever you are (everybody in this game
has a phone), the crew gets paid, and the panel moves on to the next chapter.

The REP guard rails: a chapter won't open until the crew's REP (earned from the three
DAILY jobs in quests.py) reaches its bar. The panel says how much is still owed. The story
itself pays cash, never REP -- REP is the street's respect, and the street only respects the
daily grind. That keeps the gate an actual gate instead of something the story climbs over
by itself.

What rides the wire: the chapter index, a status and a progress count, 3 bytes in SNAP_HDR.
The dialogue itself never does -- a scene is one toast carrying its key ("B:<key>"), and the
client looks the lines up in BEATS below, the same way it already looks up job names in
quests.QUESTS. Ten lines of dialogue cost the same eight bytes as one.

No pygame in here (the sim imports it; tests/test_v09.py checks).
"""

from .enums import T_SAY, T_STORY, T_MONEY, T_INFO, T_BAD

# ---- objective kinds ---------------------------------------------------------------
OBJ_DELIVER, OBJ_INSTALL, OBJ_TALK, OBJ_CARJACK, OBJ_HEAT, OBJ_BUY, OBJ_BREAKOUT, OBJ_COPCAR, \
    OBJ_DAYCOUNT, OBJ_HOT = range(10)

# ---- what the HUD shows (snapshot's story_st) ------------------------------------------
ST_LOCKED, ST_TALK, ST_ACTIVE, ST_DONE = range(4)

GIVERS = {"paige": "PAIGE", "fixer": "THE FIXER", "tommy": "TOMMY", "kingpin": "THE KINGPIN"}
GIVER_WHERE = {"paige": "AT THE SHOP", "fixer": "AT THE SHOP", "tommy": "AT HIS LOT",
               "kingpin": "AT THE TOP LOT"}


class Chapter:
    """One chapter. `goals` is the objective text for the HUD, one entry per step (most
    chapters have one step; the two-step ones -- get the heat up THEN lose it, get pinched
    THEN break out -- move to the next entry as story_n goes up). A count objective shows
    its progress as (n/N) on the end of its only goal."""
    __slots__ = ("key", "title", "giver", "rep", "cash", "kind", "arg", "goals")

    def __init__(self, key, title, giver, rep, cash, kind, arg, goals):
        self.key, self.title, self.giver, self.rep, self.cash = key, title, giver, rep, cash
        self.kind, self.arg, self.goals = kind, arg, goals

    def goal(self, n):
        if self.kind in (OBJ_DELIVER, OBJ_INSTALL, OBJ_DAYCOUNT) and self.arg > 1:
            return "%s (%d/%d)" % (self.goals[0], n, self.arg)
        return self.goals[min(n, len(self.goals) - 1)]


# REP bars: 0, 0, 1, 3, 6, 8, 10, 13, 16, 20. The first two are free (they're the tutorial);
# after that each one's a day or two of daily jobs apart (jobs pay 1-4 REP, three a day), and
# the last one sits just short of quests.ACT_THRESHOLDS' 25 so the finale lands in act III.
CHAPTERS = [
    Chapter("opening_hours", "OPENING HOURS", "paige", 0, 250, OBJ_DELIVER, 1,
            ("STEAL A CAR AND PARK IT IN THE SHOP",)),
    Chapter("tools", "TOOLS OF THE TRADE", "paige", 0, 200, OBJ_INSTALL, 1,
            ("FIT A PART TO YOUR RIDE AT THE TUNE-UP BENCH",)),
    Chapter("word_on_the_street", "WORD ON THE STREET", "fixer", 1, 150, OBJ_TALK, "tommy",
            ("GO AND SAY HELLO TO TOMMY AT HIS LOT",)),
    Chapter("moving_target", "MOVING TARGET", "paige", 3, 400, OBJ_CARJACK, None,
            ("CARJACK A CAR OUT OF TRAFFIC", "DELIVER THE CARJACKED CAR")),
    Chapter("feel_the_heat", "FEEL THE HEAT", "fixer", 6, 500, OBJ_HEAT, 50.0,
            ("GET THE HEAT UP TO 50", "NOW LOSE THEM: HEAT BACK TO 0, NO CUFFS")),
    Chapter("hostile_takeover", "HOSTILE TAKEOVER", "fixer", 8, 600, OBJ_BUY, 1,
            ("BUY TOMMY'S LOT (HOLD E AT THE FOR SALE SIGN)",)),
    Chapter("inside_job", "THE INSIDE JOB", "paige", 10, 750, OBJ_BREAKOUT, None,
            ("GET ARRESTED. ON PURPOSE. SORRY", "BREAK OUT OF THE PRECINCT. NO BAIL")),
    Chapter("blue_lights", "BLUE LIGHTS", "tommy", 13, 900, OBJ_COPCAR, None,
            ("STEAL A COP CAR WHILE ITS OFFICER'S OUT", "DELIVER THE COP CAR")),
    Chapter("audition", "THE AUDITION", "kingpin", 16, 1200, OBJ_DAYCOUNT, 3,
            ("DELIVER 3 CARS BEFORE MIDNIGHT",)),
    Chapter("the_big_one", "THE BIG ONE", "kingpin", 20, 3000, OBJ_HOT, 75.0,
            ("DELIVER A CAR WITH 75+ HEAT ON YOU",)),
]
CHAPTER_KEYS = [ch.key for ch in CHAPTERS]

# ---- the words ------------------------------------------------------------------------
# key.start plays when you take the chapter; key.end plays when it's done. (speaker, line)
# pairs; the HUD wraps and paces them, one speaker at a time, ENTER to skip ahead.
BEATS = {
    "opening_hours.start": [
        ("PAIGE", "OH GOOD, YOU'RE AWAKE. SIT DOWN. NO, NOT THERE, THAT'S WHERE MO KEEPS THE BRAKE FLUID."),
        ("PAIGE", "HERE'S THE SITUATION. UNCLE RICK LEFT US THIS SHOP, A KEI WITH THREE WORKING DOORS, "
                  "AND A LANDLORD CALLED MR. VANCE."),
        ("PAIGE", "MR. VANCE WANTS RENT EVERY MIDNIGHT. WE HAVE FORTY DOLLARS AND A COUPON FOR A FREE CAR WASH."),
        ("MO", "THE COUPON'S EXPIRED."),
        ("PAIGE", "THE COUPON'S EXPIRED. SO: GO OUT THERE, FIND A PARKED CAR, AND BRING IT HOME. "
                  "HOLD E TO BREAK IN, HOLD E AGAIN TO HOTWIRE IT."),
        ("PAIGE", "PARK IT INSIDE THE YELLOW LINE AND IT'S OURS. TRY NOT TO HIT ANYTHING. TRY HARDER THAN THAT."),
    ],
    "opening_hours.end": [
        ("PAIGE", "LOOK AT THAT. AN ACTUAL CAR. IN OUR ACTUAL SHOP. I COULD CRY."),
        ("MO", "I COULD STRIP IT. DIFFERENT KIND OF CRYING."),
        ("PAIGE", "WELCOME TO THE FAMILY BUSINESS. COME FIND ME WHEN YOU'RE READY FOR THE NEXT BIT."),
    ],
    "tools.start": [
        ("PAIGE", "RIGHT. STRIPPING CARS IS HALF THE JOB. THE OTHER HALF IS MAKING OURS LOOK LESS LIKE A LUNCHBOX."),
        ("MO", "TUNE-UP BENCH, BY THE FAR WALL. ANYTHING IN THE LOCKER, I BOLT ON. ANYTHING NOT IN THE LOCKER, "
               "YOU BUY, I BOLT ON, YOU CRY."),
        ("PAIGE", "HOLD E ON A DELIVERED CAR TO RIP A PART OFF IT. CARRY IT TO THE BENCH, PRESS E, FIT IT."),
        ("MO", "WHEELS ARE EASY. ENGINES NEED THE DOLLY. THE DOLLY NEEDS LOVE. I DON'T HAVE ANY LEFT."),
    ],
    "tools.end": [
        ("MO", "THERE. SHE'S STILL UGLY, BUT SHE'S OUR UGLY."),
        ("PAIGE", "THE FIXER'S BEEN HANGING AROUND BY THE WEST WALL ALL WEEK. GO SEE WHAT HE WANTS BEFORE HE "
                  "STARTS CHARGING US RENT TOO."),
    ],
    "word_on_the_street.start": [
        ("THE FIXER", "PSST. OVER HERE. NO, DON'T LOOK AT ME. LOOK AT THE WALL. TALK TO THE WALL."),
        ("THE FIXER", "YOU'VE GOT A PROBLEM, KID. NAME OF TOMMY CASTELLANO. RUNS THE BODY SHOP ACROSS TOWN."),
        ("THE FIXER", "EVERY CAR YOU BOOST IS A CAR TOMMY DIDN'T. HE'S NOTICED. HE'S THE KIND OF GUY WHO NOTICES."),
        ("THE FIXER", "GO INTRODUCE YOURSELF. BE POLITE. DON'T TOUCH HIS COFFEE. FOLLOW THE GOLD ARROW."),
    ],
    "word_on_the_street.end": [
        ("TOMMY", "WELL, WELL. THE KEI CREW. I'VE SEEN STRAY CATS WITH BETTER GETAWAY CARS."),
        ("TOMMY", "LET ME SAVE YOU SOME TIME: THIS TOWN'S GOT ROOM FOR ONE CHOP SHOP, AND IT'S GOT MY NAME "
                  "ON THE SIGN."),
        ("TOMMY", "RUN HOME TO PAIGE. TELL HER TOMMY SAYS HI. ACTUALLY, TELL HER TOMMY SAYS BYE."),
        ("PAIGE (ON THE PHONE)", "HE SAID WHAT? OH, IT'S ON. COME BACK TO THE SHOP. I'VE HAD AN IDEA."),
    ],
    "moving_target.start": [
        ("PAIGE", "TOMMY ONLY TAKES PARKED CARS. KNOW WHY? BECAUSE TOMMY IS SCARED OF TRAFFIC."),
        ("PAIGE", "WE ARE NOT SCARED OF TRAFFIC. WE ARE, AS OF TODAY, TRAFFIC'S WORST NIGHTMARE."),
        ("MO", "TRAFFIC WON'T STOP FOR YOU. SPIKE STRIP, ROADBLOCK OR A BANANA PEEL. THE CRATES SELL ALL THREE."),
        ("PAIGE", "STOP ONE, HOLD E TO DRAG THE DRIVER OUT, AND BRING IT HOME. BE NICE ABOUT IT. OR DON'T."),
    ],
    "moving_target.end": [
        ("PAIGE", "I JUST GOT A TEXT FROM TOMMY. IT'S JUST THE WORD 'HOW' IN CAPITALS. IT'S BEAUTIFUL."),
        ("MO", "THAT CAR STILL SMELLS LIKE THE OTHER GUY'S AIR FRESHENER. 'OCEAN BREEZE'. DISGUSTING."),
    ],
    "feel_the_heat.start": [
        ("THE FIXER", "WORD IS THE PRECINCT GOT A NEW CAPTAIN. CAPTAIN DORSEY. LOVES PAPERWORK. HATES FUN."),
        ("THE FIXER", "MY CLIENTS WANT TO KNOW HOW FAST HER BOYS REACT. YOU'RE GOING TO TELL THEM."),
        ("THE FIXER", "GET HALF THE CITY LOOKING FOR YOU -- FIFTY HEAT -- THEN DISAPPEAR."),
        ("THE FIXER", "ALLEYS. CORNERS. THE SHOP WITH THE DOORS SHUT. A CARDBOARD BOX, IF YOU'VE NO DIGNITY. "
                      "JUST DON'T GET CUFFED."),
    ],
    "feel_the_heat.end": [
        ("THE FIXER", "ALL THOSE SIRENS AND NOT ONE SET OF CUFFS. MY CLIENTS ARE DELIGHTED. CAPTAIN DORSEY IS NOT."),
        ("CAPTAIN DORSEY (SCANNER)", "ALL UNITS: WHOEVER THAT WAS, I WANT THEM. I WANT THEM IN A FRAME. "
                                     "ON MY WALL."),
        ("THE FIXER", "SHE'S GOING TO BE A PROBLEM. GOOD FOR BUSINESS. BAD FOR YOUR BLOOD PRESSURE."),
    ],
    "hostile_takeover.start": [
        ("THE FIXER", "HERE'S A FUNNY THING. TOMMY DOESN'T OWN HIS LOT. HE RENTS IT. FROM A MAN WHO OWES ME A FAVOUR."),
        ("THE FIXER", "THE LOT'S UP FOR SALE. TOMMY DOESN'T KNOW. TOMMY'S GOING TO FIND OUT WHEN YOU BUY IT."),
        ("PAIGE", "IS THIS... IS THIS LEGAL?"),
        ("THE FIXER", "COMPLETELY. ONLY LEGAL THING I'VE EVER DONE. FEELS WEIRD. BRING CASH."),
    ],
    "hostile_takeover.end": [
        ("TOMMY", "YOU... BOUGHT MY... I'VE BEEN PARKING HERE FOR ELEVEN YEARS!"),
        ("PAIGE (ON THE PHONE)", "AND NOW YOU CAN PARK SOMEWHERE ELSE. BYEEE."),
        ("TOMMY", "THIS ISN'T OVER, KEI CREW. THIS ISN'T EVEN THE MIDDLE."),
    ],
    "inside_job.start": [
        ("PAIGE", "BAD NEWS. MO'S COUSIN DEZ GOT PINCHED LAST NIGHT. JOYRIDING A HEARSE. DON'T ASK."),
        ("MO", "HE'S GOT MY GOOD SOCKET SET IN HIS COAT. THE TEN-MIL. I NEED THAT TEN-MIL."),
        ("PAIGE", "SO HERE'S THE PLAN, AND I WANT IT ON RECORD THAT I HATE IT: YOU GET ARRESTED. ON PURPOSE."),
        ("PAIGE", "FIND DEZ IN THE LOCKUP, GRAB THE SOCKETS, BREAK OUT. BAIL DOESN'T COUNT. BAIL IS FOR "
                  "QUITTERS AND DENTISTS."),
        ("MO", "THE DESK SERGEANT LEAVES THE IMPOUND BIKES OUT FRONT WITH THE KEYS IN. JUST SAYING."),
    ],
    "inside_job.end": [
        ("DEZ (OVER THE WALL)", "TELL MO I'M KEEPING THE RATCHET. TELL HIM IT WAS A GIFT. FROM ME. TO ME."),
        ("MO", "MY TEN-MIL. HELLO, BEAUTIFUL. I MISSED YOU."),
        ("PAIGE", "ONE OF THESE DAYS WE'LL DO A JOB THAT DOESN'T END IN A CHASE. TODAY IS NOT THAT DAY."),
    ],
    "blue_lights.start": [
        ("TOMMY", "OKAY. OKAY. I'VE HAD SOME TIME TO THINK, STANDING HERE ON THE LOT YOU STOLE FROM ME."),
        ("TOMMY", "I DON'T LIKE YOU. BUT I LIKE CAPTAIN DORSEY LESS. SHE TOWED MY MUM'S CAR. MY MUM'S."),
        ("TOMMY", "I'VE GOT A BUYER WHO'LL PAY STUPID MONEY FOR A REAL POLICE INTERCEPTOR. LIGHTS, SIREN, THE LOT."),
        ("TOMMY", "GET A COP TO CHASE YOU ON FOOT. WHEN THE OFFICER JUMPS OUT, YOU JUMP IN. BRING IT TO YOUR SHOP."),
    ],
    "blue_lights.end": [
        ("TOMMY (ON THE PHONE)", "YOU ACTUALLY DID IT. WITH THE SIREN ON. THROUGH THE FISH MARKET."),
        ("CAPTAIN DORSEY (SCANNER)", "SOMEBODY STOLE UNIT TWELVE? SOMEBODY STOLE MY UNIT TWELVE?"),
        ("TOMMY (ON THE PHONE)", "...TRUCE? TRUCE. I'LL TELL THE KINGPIN ABOUT YOU. HE LIKES PEOPLE WHO ARE "
                                 "BAD AT STAYING OUT OF TROUBLE."),
    ],
    "audition.start": [
        ("THE KINGPIN", "SIT. YOU'RE THE KEI PEOPLE. TOMMY SPEAKS OF YOU WITH A MIXTURE OF HATRED AND RESPECT. "
                        "MOSTLY HATRED."),
        ("THE KINGPIN", "I RUN DOWNTOWN. EVERYTHING WITH WHEELS, SOONER OR LATER, PASSES THROUGH MY HANDS."),
        ("THE KINGPIN", "MY SUPPLIER RETIRED. BY WHICH I MEAN HE MOVED TO PORTUGAL WITH MY MONEY. I NEED A NEW ONE."),
        ("THE KINGPIN", "THREE CARS. ONE DAY. BEFORE MIDNIGHT. SHOW ME YOU'RE A BUSINESS AND NOT A HOBBY."),
    ],
    "audition.end": [
        ("THE KINGPIN (ON THE PHONE)", "THREE CARS IN ONE DAY, AND YOU STILL MADE RENT. I'M ALMOST MOVED."),
        ("PAIGE", "DID THE KINGPIN JUST COMPLIMENT US? WRITE THAT DOWN. MO, WRITE THAT DOWN."),
        ("MO", "I DON'T HAVE A PEN. I HAVE A TEN-MIL."),
    ],
    "the_big_one.start": [
        ("THE KINGPIN", "CAPTAIN DORSEY IS HOLDING A PRESS CONFERENCE. SHE'S CALLING IT 'OPERATION CLEAN STREETS'."),
        ("THE KINGPIN", "I WOULD LIKE HER TO BE HOLDING THAT PRESS CONFERENCE WHILE YOU DELIVER A CAR PAST HER. "
                        "LOUDLY."),
        ("THE KINGPIN", "GET THE WHOLE PRECINCT ON YOUR BUMPER -- SEVENTY-FIVE HEAT -- AND DRIVE IT HOME ANYWAY."),
        ("PAIGE (ON THE PHONE)", "FOR THE RECORD, THIS IS THE DUMBEST PLAN ANYONE HAS EVER HAD."),
        ("THE KINGPIN", "FOR THE RECORD, IT PAYS THREE THOUSAND DOLLARS."),
        ("PAIGE (ON THE PHONE)", "...FOR THE RECORD, I LOVE IT."),
    ],
    "the_big_one.end": [
        ("CAPTAIN DORSEY (ON THE NEWS)", "...AND I WANT TO ASSURE THE PUBLIC THAT OUR STREETS ARE... IS THAT A CAR? "
                                         "WHY IS IT COMING THIS WAY?"),
        ("THE KINGPIN (ON THE PHONE)", "MAGNIFICENT. DOWNTOWN IS YOURS. I'M RETIRING. PORTUGAL, I HEAR, IS LOVELY."),
        ("TOMMY (ON THE PHONE)", "FINE. FINE! YOU'RE THE BEST CHOP SHOP IN TOWN. IT PHYSICALLY HURTS TO SAY THAT."),
        ("PAIGE", "UNCLE RICK WOULD BE SO PROUD. OR ARRESTED. WITH RICK IT WAS ALWAYS ONE OR THE OTHER."),
        ("MO", "SAME TIME TOMORROW?"),
        ("PAIGE", "SAME TIME TOMORROW."),
    ],
}

# said by a giver whose chapter the crew doesn't have the REP for yet
LOCKED_LINES = {
    "paige": "NOT YET. NOBODY'S HEARD OF US. DO SOME OF TODAY'S JOBS FIRST. (%d MORE REP)",
    "fixer": "MY CLIENTS DON'T TALK TO NOBODIES. COME BACK WITH A REPUTATION. (%d MORE REP)",
    "tommy": "I DON'T DO BUSINESS WITH AMATEURS. GO EARN SOME STREET CRED. (%d MORE REP)",
    "kingpin": "WHO LET YOU IN? COME BACK WHEN PEOPLE SAY YOUR NAME QUIETLY. (%d MORE REP)",
}
# said by a giver whose chapter is under way (the objective, in their words)
NAG_LINES = {
    "paige": "STILL WAITING ON YOU. %s.",
    "fixer": "CLOCK'S TICKING, KID. %s.",
    "tommy": "WELL? %s. I'M NOT GETTING ANY YOUNGER.",
    "kingpin": "I DON'T REPEAT MYSELF. ...%s.",
}
THE_END = "THE END. (THE CITY'S STILL FULL OF CARS, THOUGH.)"


def chapter(i):
    return CHAPTERS[i] if 0 <= i < len(CHAPTERS) else None


class Story:
    """World mixin. Crew-shared, like cash, heat and the daily jobs: any crewmate can move it on."""

    def _init_story(self):
        self.story_ch = 0               # index into CHAPTERS; len(CHAPTERS) = the story's over
        self.story_active = False       # taken (talked to the giver) and under way
        self.story_n = 0                # progress: a count, or which step of a two-step chapter
        self.story_flags = {}           # per-chapter scratch (which car we're tracking, ...)
        self.story_told = False         # "new chapter!" toast already said for this one

    def story_status(self):
        ch = chapter(self.story_ch)
        if ch is None:
            return ST_DONE
        if self.story_active:
            return ST_ACTIVE
        return ST_TALK if self.story_points >= ch.rep else ST_LOCKED

    def _story_beat(self, key):
        if key in BEATS:
            self.toast("B:" + key, T_STORY)

    def _story_start(self):
        ch = chapter(self.story_ch)
        self.story_active = True
        self.story_n = 0
        self.story_flags = {}
        self._story_beat(ch.key + ".start")
        if ch.kind == OBJ_BUY and self._story_lot_owned():
            self._story_complete()          # (bought it before anybody asked you to. Keen.)

    def _story_complete(self):
        ch = chapter(self.story_ch)
        if ch is None:
            return
        self._earn(ch.cash)
        self._story_beat(ch.key + ".end")
        self.toast("STORY: %s DONE (+$%d)" % (ch.title, ch.cash), T_MONEY)
        self.story_ch += 1
        self.story_active = False
        self.story_n = 0
        self.story_flags = {}
        self.story_told = False
        if self.story_ch >= len(CHAPTERS):
            self.toast(THE_END, T_MONEY)

    def _story_talk(self, key, name):
        """Somebody pressed E at a story NPC. True = the story used the conversation (the
        NPC's usual small talk is skipped); False = say your usual thing too."""
        ch = chapter(self.story_ch)
        if ch is None:
            return False
        if self.story_active and ch.kind == OBJ_TALK and ch.arg == key:
            self._story_complete()
            return True
        if ch.giver != key:
            return False
        st = self.story_status()
        if st == ST_TALK:
            self._story_start()
            return True
        if st == ST_LOCKED:
            self._say(name, LOCKED_LINES[key] % (ch.rep - self.story_points))
        elif st == ST_ACTIVE:
            self._say(name, NAG_LINES[key] % ch.goal(self.story_n))
        return False

    def _story_lot_owned(self):
        """Tommy's lot: the tier-1 fence."""
        for i in range(1, len(self.shop_owned)):
            if i - 1 < len(self.map.fence_shops) and self.map.fence_shops[i - 1]["tier"] == 1:
                return self.shop_owned[i]
        return False

    def _story_event(self, kind, car=None, value=0.0):
        """One call from each hook that matters (see sim/police/garage/quests)."""
        if not self.story_active:
            return
        ch = chapter(self.story_ch)
        if ch is None:
            return
        k = ch.kind
        if k == OBJ_DELIVER and kind == "deliver":
            self._story_count(ch)
        elif k == OBJ_INSTALL and kind == "install":
            self._story_count(ch)
        elif k == OBJ_DAYCOUNT and kind == "deliver":
            self._story_count(ch)
        elif k == OBJ_HOT and kind == "deliver":
            if value >= ch.arg:
                self._story_complete()
            else:
                self.toast("STORY: NOT HOT ENOUGH (%d HEAT). THE KINGPIN WANTS %d+" % (value, ch.arg), T_INFO)
        elif k == OBJ_CARJACK:
            if kind == "carjack":
                self.story_flags["car"] = car.id
                self.story_n = 1
            elif kind == "deliver" and car is not None and car.id == self.story_flags.get("car"):
                self._story_complete()
        elif k == OBJ_COPCAR:
            if kind == "steal" and car is not None and getattr(car, "copcar", False):
                self.story_flags["car"] = car.id
                self.story_n = 1
            elif kind == "deliver" and car is not None and car.id == self.story_flags.get("car"):
                self._story_complete()
        elif k == OBJ_BUY and kind == "buy":
            if self._story_lot_owned():
                self._story_complete()
        elif k == OBJ_BREAKOUT:
            if kind == "arrest":
                self.story_n = 1
            elif kind == "breakout" and self.story_n >= 1:
                self._story_complete()
            elif kind == "bail" and self.story_n >= 1:
                self.story_n = 0
                self.toast("STORY: BAIL DOESN'T COUNT. GET PINCHED AND DO IT PROPERLY.", T_BAD)
        elif k == OBJ_HEAT and kind == "arrest" and self.story_n >= 1:
            self.story_n = 0
            self.toast("STORY: CUFFED. THE FIXER'S CLIENTS ARE UNIMPRESSED. AGAIN.", T_BAD)

    def _story_count(self, ch):
        self.story_n += 1
        if self.story_n >= ch.arg:
            self._story_complete()

    def _story_new_day(self):
        """Midnight: THE AUDITION's count is "before midnight", so it starts again."""
        ch = chapter(self.story_ch)
        if ch is not None and self.story_active and ch.kind == OBJ_DAYCOUNT and self.story_n > 0:
            self.story_n = 0
            self.toast("STORY: MIDNIGHT. THE KINGPIN'S COUNT STARTS AGAIN.", T_INFO)

    def _story_tick(self, dt):
        ch = chapter(self.story_ch)
        if ch is None:
            return
        if not self.story_active:
            if not self.story_told and self.players and self.story_points >= ch.rep:
                self.story_told = True
                self.toast("NEW STORY CHAPTER: %s. TALK TO %s." % (ch.title, GIVERS[ch.giver]), T_MONEY)
            return
        if ch.kind == OBJ_HEAT:
            if self.story_n == 0 and self.heat >= ch.arg:
                self.story_n = 1
                self.toast("STORY: THAT'S FIFTY. NOW LOSE THEM.", T_INFO)
            elif self.story_n == 1 and self.heat <= 0.0:
                self._story_complete()
