"""The crew you can be (v0.16). DATA ONLY, no pygame: a character is one dict, and each perk is a
multiplier under `stats`. Code asks `stat(char, key)` and gets 1.0 if the character has no opinion,
so a new character (append-only: the id is what rides the wire) is a table entry, not a new branch.
A character is who joined, not crew progress, so it isn't saved: reconnect and pick again."""
from . import config as C

# stats keys in use: stamina_max, stamina_regen, strip_time, breakin_time, hotwire_time,
# alarm_cut_time, alarm_wires (multiplies the number of wires), sale_bonus (money from his sales),
# fee_mult (bail and papers), theft_heat (x the heat of a break-in / carjack), breakin_alarm (x0 = his
# window-smash is silent)
CHARACTERS = (
    {"id": 0, "name": "DASH", "title": "ATHLETE", "perk": "MORE STAMINA, FASTER RECOVERY",
     "blurb": "RUNS EVERYWHERE. HAS NEVER ONCE WALKED.",
     "stats": {"stamina_max": C.CHAR_DASH_STAMINA_MAX, "stamina_regen": C.CHAR_DASH_STAMINA_REGEN}},
    {"id": 1, "name": "SPANNER", "title": "GREASE MONKEY", "perk": "STRIPS PARTS 40% FASTER",
     "blurb": "SMELLS OF 10W-40. CAN UNBOLT A CAR IN HIS SLEEP.",
     "stats": {"strip_time": C.CHAR_SPANNER_STRIP_TIME}},
    {"id": 2, "name": "SLIM", "title": "LIGHT FINGERS", "perk": "FAST, SILENT BREAK-INS, HALF THE HEAT",
     "blurb": "LOCKS ARE JUST SUGGESTIONS. ALARMS ARE SHY.",
     "stats": {"breakin_time": C.CHAR_SLIM_BREAKIN_TIME, "hotwire_time": C.CHAR_SLIM_HOTWIRE_TIME,
               "alarm_cut_time": C.CHAR_SLIM_ALARM_CUT_TIME, "alarm_wires": C.CHAR_SLIM_ALARM_WIRES,
               "theft_heat": C.CHAR_SLIM_THEFT_HEAT, "breakin_alarm": C.CHAR_SLIM_BREAKIN_ALARM}},
    {"id": 3, "name": "SMOOTH", "title": "SMOOTH TALKER", "perk": "+10% ON SALES, HALF PRICE BAIL",
     "blurb": "COULD SELL A CAR BACK TO ITS OWNER. HAS.",
     "stats": {"sale_bonus": C.CHAR_SMOOTH_SALE_BONUS, "fee_mult": C.CHAR_SMOOTH_FEE_MULT}},
)
N_CHARS = len(CHARACTERS)


def clamp_char(c):
    """Anything that isn't a known id (garbage off the wire, None) is character 0."""
    try:
        c = int(c)
    except (TypeError, ValueError):
        return 0
    return c if 0 <= c < N_CHARS else 0


def stat(char, key):
    """The multiplier for `key` (1.0 when this character doesn't care about it)."""
    return CHARACTERS[clamp_char(char)].get("stats", {}).get(key, 1.0)


def stamina_max(char):
    return C.STAMINA_MAX * stat(char, "stamina_max")


def alarm_wires(char):
    return max(1, int(round(C.ALARM_CUT_WIRES * stat(char, "alarm_wires"))))
