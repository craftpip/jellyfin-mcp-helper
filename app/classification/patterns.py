"""Shared regex patterns for media classification.

Single source of truth for S/E detection. Includes JellyJake-ported
robustness patterns (x-notation, word-form S+E, sane caps, codec guards).
"""
from __future__ import annotations

import re

EXTRA_MARKERS = re.compile(r"\b(ncop\d*|nced\d*|op\d*|ed\d*|sp\d*|ova|ona|special|extras?|featurettes?|bonus|recap|trailer)\b", re.IGNORECASE)
SAMPLE_MARKERS = re.compile(r"\bsample\b", re.IGNORECASE)
_GENERIC_EXTRA_SET = {
    "ed", "op", "nc", "nced", "ncop", "ova", "ona", "sp", "special", "extras", "extra",
    "featurette", "featurettes", "bonus", "recap", "trailer", "short", "interview", "deleted",
    "behindthescenes",
}
_COLLECTION_HINT_RE = re.compile(r"\b(collection|anthology|complete|boxset)\b", re.IGNORECASE)
SEASON_EPISODE_RE = re.compile(r"s\d{1,2}e\d{1,3}", re.IGNORECASE)
SPECIAL_TAG_RE = re.compile(r"(?:^|[\s\[\]()_.-])sp(?:[\s\[\]()_.-]|$)", re.IGNORECASE)
DECIMAL_EPISODE_RE = re.compile(r"(?:^|[^a-z0-9])s\d{1,2}e\d{1,3}\.\d+(?:[^a-z0-9]|$)", re.IGNORECASE)
SEASON_ONLY_RE = re.compile(r"season\s*\d{1,2}|s\d{1,2}\b", re.IGNORECASE)
SEASON_EPISODE_TOKEN_RE = re.compile(
    r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})e(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_DASH_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})\s*-\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_WORD_DASH_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])season\s*(?P<season>\d{1,2})\s*-\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
SEASON_FOLDER_RE = re.compile(r"(?:^|[^a-z0-9])(?:season\s*|s)(?P<season>\d{1,2})(?:[^a-z0-9]|$)", re.IGNORECASE)
BARE_EPISODE_RE = re.compile(r"(?:^|[^a-z0-9])(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)", re.IGNORECASE)
CONTAINED_BARE_EPISODE_RE = re.compile(
    r"^(?P<episode>\d{1,3})(?:v\d+)?\s*(?:[-_ ]|\.(?!\d))\s*(?P<title>\S.*)$",
    re.IGNORECASE,
)
MOVIE_MARKER_RE = re.compile(r"\bmovie[\s_.-]*\d{1,3}\b", re.IGNORECASE)
FRANCHISE_MOVIE_MARKER_RE = re.compile(r"\bs\d{1,2}m\d{1,2}\b", re.IGNORECASE)

FOREIGN_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:episodio|episode|capitulo|capitolo|capítulo|chapitre|épisode|kapitel)\s*(\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

_SEASON_MARKER_RE = re.compile(r"\s+(?:S\d{1,2}(?:[-–_]\s*S?\d{1,2})?(?:\+?P\d{1,2})?(?:\+SP)?|\(?Season\s*\d{1,2}(?:\s*[-–]\s*\d{1,2})?\)?)(?=\s|[-,._]|$)", re.IGNORECASE)
_SEASON_PLUS_TEXT_RE = re.compile(r"\s+S\d{1,2}\+.*$", re.IGNORECASE)
_TECH_TAG_RE = re.compile(
    r"\s+\[?(?:\d{3,4}p|(?:Dual\s+)?Audio|BDRip|BluRay|WEB[.-]?DL|WebRip|HDRip|x264|x265|HEVC|10\s*bit)",
    re.IGNORECASE,
)
_TRAILING_GROUP_RE = re.compile(r"\s*[-–]\s*[A-Za-z0-9]+$")
_TRAILING_BRACKET_RE = re.compile(r"\s*\[.*?\]\s*$")
_TRAILING_PAREN_TECH_RE = re.compile(
    r"\s*\([^)]*\b(?:\d{3,4}p|x264|x265|HEVC|BDRip|BluRay|WEB[.-]?DL|WEBRip|HDRip|Dual\s*Audio|10\s*bit)\b[^)]*\)\s*$",
    re.IGNORECASE,
)
_LEADING_BRACKET_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")


_CRC_BRACKETS_RE = re.compile(r"\s*\[[A-Fa-f0-9]{6,10}\]\s*$")
_CRC_PAREN_RE = re.compile(r"\s*\([A-Fa-f0-9]{6,10}\)\s*$")
_FILENAME_EP_TITLE_RE = re.compile(r"S\d{1,2}E\d{1,3}[-. ]+(.+)", re.IGNORECASE)

# --- JellyJake-ported robust S/E patterns (single-file semantics, no kind change) ---

# Season caps: seasons are 1..60, episodes 1..500. 4-digit values are
# years/resolutions glued in standalone ("S02 - 2019", "Season 2 - 1080p")
# and must never become episode numbers.
SEASON_MAX = 60
EPISODE_MAX = 500
# Codec numbers are never episode numbers in x-notation.
CODEC_EPISODES = frozenset({264, 265})

# Word-form S+E without dash: "Season 1 Episode 5", "Season 2 Ep 03".
# The season must NOT be dropped when a word-form episode follows.
SEASON_WORD_EPISODE_RE = re.compile(
    r"(?:^|[^a-z0-9])season\s*(?P<season>\d{1,2})\s*(?:episode|episodes|eps?|ep)\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

# Episode-only markers: "E05", "Episode 5", "Ep 12" (season carried separately).
EP_ONLY_S_RE = re.compile(r"(?:^|[^a-z0-9])e(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)", re.IGNORECASE)
EP_ONLY_WORD_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:episode|episodes|eps?|ep)\s*(?P<episode>\d{1,3})(?:v\d+)?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

# x-notation: "1x05", "2x03". Guarded in code (season <= 60, ep not 264/265,
# no digit/dot directly before, never dimensions like 1920x1080).
X_NOTATION_RE = re.compile(
    r"(?<![\d.])(?<!\d )(?:^|[^a-z0-9])(?P<season>\d{1,2})\s*x\s*(?P<episode>\d{1,3})(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

# Anime fansub finale: "S2 - 12 END" / "Season 2 - 12 END" is S02E12,
# never a season range.
END_EPISODE_S_RE = re.compile(
    r"(?:^|[^a-z0-9])s(?P<season>\d{1,2})\s*[-–]\s*(?P<episode>\d{1,3})\s*END(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
END_EPISODE_WORD_RE = re.compile(
    r"(?:^|[^a-z0-9])season\s*(?P<season>\d{1,2})\s*[-–]\s*(?P<episode>\d{1,3})\s*END(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

# Anime "Part"-episode: "Part 2 - 06" with a season anchor elsewhere in the
# label is an episode designator, not a split pack.
PART_EP_RE = re.compile(r"\bpart\s*\d+\s*[-–]\s*0*(?P<episode>\d{1,3})(?![\w])", re.IGNORECASE)

# 4-digit year or resolution standing where an episode number would go.
YEAR_OR_RES_RE = re.compile(r"\b(?:19\d{2}|20\d{2}|480p?|576p?|720p?|1080p?|2160p?)\b", re.IGNORECASE)
