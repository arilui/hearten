"""
Match recipe food words to a USDA food description.

USDA foods are named "Head, qualifier, qualifier" ("Kale, raw"; "Beans, black,
mature seeds, canned"). Some heads are just a category ("Spices, cumin seed";
"Oil, olive, salad or cooking"), and then the next segment is the real head.

The ranking rewards descriptions whose words are covered by the recipe text,
especially the head, prefers plain ingredients over prepared dishes, branded
products and food parts ("skin only"), and prefers raw forms unless the recipe
says otherwise. When several variants still tie ("Tomatoes, green" vs
"Tomatoes, red, ripe"), an optional usage prior breaks the tie: how often
USDA's own survey recipes use each ingredient. Every score component is kept,
so a match can be explained.
"""

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

STOPWORDS = {"and", "or", "with", "of", "the", "a", "an", "in", "for", "to", "type",
             "style", "boneless", "bone", "nfs", "ns", "as", "made", "from", "large",
             "medium", "small", "mix", "includes", "skinless"}

# Words that describe a common default rather than a distinct variety. They count
# when the recipe uses them, but cost nothing when it doesn't.
FREE_WORDS = {"whole", "raw", "fresh", "regular", "plain", "all", "varieties", "variety",
              "commercial", "mixed", "species", "unprepared", "uncooked", "enriched",
              "unenriched", "fluid", "mature", "seed", "year", "round", "average", "ripe",
              "table", "salad", "cooking", "common", "solids", "drained", "pack", "milkfat",
              "vitamin", "added", "d"}

# Phrases marking the everyday version of a food among its variants.
GENERIC_MARKERS = re.compile(
    r"all commercial varieties|year round average|mixed species|all types|all varieties"
    r"|\bcommon\b|\bregular\b"
)

# Heads that only name a category; the next segment is the real head.
CATEGORY_HEADS = {"spices", "leavening agents", "oil", "sugars", "syrups", "soup", "nuts",
                  "seeds", "beans", "sauce", "beverages", "fish", "crustaceans",
                  "mollusks", "cereals", "alcoholic beverage", "salad dressing", "vinegar",
                  "sweeteners", "game meat"}

# Words that mark a prepared dish or special product; penalized unless asked for.
DISH_WORDS = {"soup", "salad", "sandwich", "pie", "casserole", "baby", "infant", "toddler",
              "formula", "restaurant", "fast", "school", "dinner", "entree", "frozen",
              "meal", "kit", "puree", "pudding", "smoothie", "shake", "drink", "beverage",
              "sauce", "dip", "spread", "bar", "snack", "cereal", "candy", "dessert",
              "stew", "chowder", "burrito", "taco", "pizza", "burger", "roll", "dumpling",
              "souffle", "bread", "lemonade", "limeade"}

# Segments naming only part of a food ("Potatoes, raw, skin"; "Broccoli, leaves").
PART_SEGMENT = re.compile(
    r"^(?:skin|skin only|peel|leaves|stalks|tops only|flower clusters|giblets|separable fat)$"
)

# Product variants to avoid unless asked for.
ODD_WORDS = {"imitation": 0.3, "sprouted": 0.2, "dehydrated": 0.15, "freeze": 0.15,
             "substitute": 0.3, "replacement": 0.3, "diet": 0.15, "fortified": 0.08,
             "solution": 0.1, "concentrate": 0.1,
             # Default to the regular product; sodium is judged on what's actually used.
             "lowsodium": 0.15, "unsalted": 0.08, "grass": 0.1}

COOKING_WORDS = {"cooked", "boiled", "baked", "roasted", "fried", "grilled", "steamed",
                 "sauteed", "broiled", "stewed", "canned", "braised", "microwaved",
                 "prepared", "toasted"}
RAW_WORDS = {"raw", "unprepared", "uncooked"}
GRAIN_WORDS = {"pasta", "rice", "couscous", "oat", "noodle", "lentil", "bean", "barley",
               "quinoa", "spaghetti", "macaroni"}

# Recipe phrasing -> USDA phrasing. Applied to the recipe text before matching.
SYNONYMS = [
    (r"\ball[- ]purpose flour\b", "flour white all purpose"),
    (r"\bwhole[- ]wheat flour\b", "wheat flour whole grain"),
    (r"\bscallions?\b|\bgreen onions?\b|\bspring onions?\b", "onion spring scallion green"),
    (r"\bgarbanzo beans?\b", "chickpea"),
    (r"\b(?:confectioners'?|powdered|icing) sugar\b", "sugar powdered"),
    (r"\bgranulated sugar\b|\bwhite sugar\b", "sugar granulated"),
    (r"\bbell peppers?\b", "pepper sweet"),
    (r"\bheavy (?:whipping )?cream\b", "cream heavy whipping"),
    (r"\bhalf[- ]and[- ]half\b", "cream half and half"),
    (r"\bsour cream\b", "cream sour cultured"),
    (r"\bextra[- ]virgin olive oil\b|\bevoo\b", "olive oil"),
    (r"\bcilantro\b", "cilantro coriander"),
    (r"\bzucchini\b", "zucchini squash summer"),
    (r"\bground beef\b", "beef ground"),
    (r"\bground turkey\b", "turkey ground"),
    (r"\bkosher salt\b|\bsea salt\b|\btable salt\b", "salt table"),
    (r"\bblack pepper\b", "spices pepper black"),
    (r"\bbaking soda\b", "baking soda sodium bicarbonate"),
    (r"\bparmesan\b", "cheese parmesan"),
    (r"\bcheddar\b", "cheese cheddar"),
    (r"\bmozzarella\b", "cheese mozzarella"),
    (r"\bfeta\b", "cheese feta"),
    (r"\bgreek yogurt\b", "yogurt greek"),
    (r"\b(?:rolled|old[- ]fashioned|quick[- ]cooking|quick) oats\b", "oats regular quick"),
    (r"\btomato paste\b", "tomato products paste"),
    (r"\btomato sauce\b", "tomato products sauce"),
    (r"\b(?:spaghetti|penne|linguine|fettuccine|rigatoni|fusilli|rotini|farfalle|ziti)\b",
     "pasta"),
    (r"\bketchup\b", "catsup"),
    (r"\bmayo\b", "mayonnaise"),
    (r"\bfill?ets?\b", " "),
    (r"\bshrimps?\b", "shrimp crustaceans"),
    (r"\bapple cider vinegar\b|\bcider vinegar\b", "vinegar cider"),
    (r"\bcocoa powder\b", "cocoa dry powder"),
    (r"\bpearl(?:ed)? barley\b", "barley pearled"),
    (r"^\s*water\s*$", "water tap"),
    (r"^\s*mushrooms?\s*$", "mushrooms white"),
    (r"\b(?:broth|stock)\b", "broth soup"),
    (r"\bfresh\b", "fresh raw"),
]

# Description and recipe text alike: one spelling for salt and sodium wording.
NORMALIZE = [
    (r"\((?:includes foods for usda'?s food distribution program|may contain additives"
     r"[^)]*)\)", " "),
    (r"\b(?:less/reduced|reduced|lower|low|less)[- ]sodium\b", " lowsodium "),
    (r"\b(?:without (?:added )?salt(?: added)?|no salt added|salt not added"
     r"(?: in processing)?|unsalted)\b", " unsalted "),
    (r"\b(?:with (?:added )?salt(?: added)?|salt added(?: in processing)?|salted)\b",
     " salted "),
]


def _singular(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("ches"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(text: str) -> str:
    text = text.lower()
    for pattern, replacement in NORMALIZE:
        text = re.sub(pattern, replacement, text)
    return text


def tokens(text: str) -> list[str]:
    # Percentages stay ("2% milk", "93% lean") since they tell variants apart.
    words = re.findall(r"\d+(?:\.\d+)?%|[a-z]+", text.lower())
    return [_singular(w) for w in words if w not in STOPWORDS]


def apply_synonyms(text: str) -> str:
    text = normalize(text)
    for pattern, replacement in SYNONYMS:
        text = re.sub(pattern, replacement, text)
    return text


def _segments(description: str) -> list[str]:
    return [s.strip() for s in normalize(description).split(",") if s.strip()]


def _head_and_category(description: str) -> tuple[list[str], set[str]]:
    segments = _segments(description)
    if not segments:
        return [], set()
    if segments[0] in CATEGORY_HEADS and len(segments) > 1:
        return tokens(segments[1]), set(tokens(segments[0]))
    return tokens(segments[0]), set()


def _is_branded(description: str) -> bool:
    # Brand names are written in capitals: "CHOBANI", "UNCLE BEN'S". USDA's own
    # notes ("Includes foods for USDA's Food Distribution Program") aren't brands.
    text = re.sub(r"\bUSDA\b|\bNLEA\b|\bNS\b|\bNFS\b", " ", description)
    return bool(re.search(r"\b[A-Z][A-Z'&]{2,}\b", text))


@dataclass
class Candidate:
    food_code: int
    description: str
    score: float
    coverage: float
    head_match: float
    extra_words: int
    penalties: list[str]


class FoodIndex:
    """
    foods: (code, description) pairs.
    usage: optional count of USDA survey recipes using each food, as a tie-breaker.
    bonus: optional fixed score adjustment per food (e.g. to prefer one data source).
    """

    def __init__(self, foods: list[tuple[int, str]], usage: Mapping[int, int] | None = None,
                 bonus: Mapping[int, float] | None = None):
        self.foods = foods
        self.usage = usage or {}
        self.bonus = bonus or {}
        self.food_tokens = [tokens(normalize(desc)) for _, desc in foods]
        heads = [_head_and_category(desc) for _, desc in foods]
        self.head_tokens = [h for h, _ in heads]
        self.category_tokens = [c for _, c in heads]
        self.segments = [_segments(desc) for _, desc in foods]
        self.branded = [_is_branded(desc) for _, desc in foods]
        self.generic = [bool(GENERIC_MARKERS.search(desc.lower())) for _, desc in foods]
        df = Counter(t for toks in self.food_tokens for t in set(toks))
        n = len(foods)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self.by_token: dict[str, list[int]] = {}
        for i, toks in enumerate(self.food_tokens):
            for t in set(toks):
                self.by_token.setdefault(t, []).append(i)

    def search(self, food_text: str, limit: int = 5) -> list[Candidate]:
        query = tokens(apply_synonyms(food_text))
        if not query:
            return []
        qset = set(query)
        q_weight = sum(self.idf.get(t, 1.0) for t in qset)
        pool = {i for t in qset for i in self.by_token.get(t, [])}
        wants_cooked = bool(qset & COOKING_WORDS)
        is_grain = bool(qset & GRAIN_WORDS)

        results = []
        for i in pool:
            code = self.foods[i][0]
            ftoks = set(self.food_tokens[i])
            matched = qset & ftoks
            coverage = sum(self.idf.get(t, 1.0) for t in matched) / q_weight
            head = set(self.head_tokens[i])
            head_match = len(head & qset) / len(head) if head else 0.0
            extra = ftoks - qset - FREE_WORDS - COOKING_WORDS - self.category_tokens[i]
            penalties = []
            score = coverage + 0.6 * head_match - 0.04 * len(extra)

            dish = (ftoks & DISH_WORDS) - qset
            if dish:
                score -= 0.35
                penalties.append(f"dish/product word: {', '.join(sorted(dish))}")
            if self.branded[i]:
                score -= 0.3
                penalties.append("branded product")
            parts = [s for s in self.segments[i] if PART_SEGMENT.match(s)]
            if parts and not qset & set(tokens(" ".join(parts))):
                score -= 0.3
                penalties.append(f"part of the food only: {', '.join(parts)}")
            for word, cost in ODD_WORDS.items():
                if word in ftoks and word not in qset:
                    score -= cost
                    penalties.append(f"unusual variant: {word}")

            raw_like = ftoks & RAW_WORDS or (is_grain and "dry" in ftoks)
            if raw_like and not wants_cooked:
                score += 0.12
            if wants_cooked and raw_like:
                score -= 0.2
                penalties.append("raw, but recipe says cooked")
            if not wants_cooked and ftoks & COOKING_WORDS:
                score -= 0.1
                penalties.append("cooked or processed, recipe didn't say so")
            if self.generic[i]:
                score += 0.06
            uses = self.usage.get(code, 0)
            if uses:
                score += min(0.04 * math.log1p(uses), 0.25)
            score += self.bonus.get(code, 0.0)

            results.append(Candidate(
                food_code=code, description=self.foods[i][1],
                score=round(score, 4), coverage=round(coverage, 3),
                head_match=round(head_match, 3), extra_words=len(extra), penalties=penalties,
            ))

        results.sort(key=lambda c: (-c.score, len(c.description)))
        return results[:limit]


def query_text(parsed) -> str:
    """The text to search for a parsed line, with hints from its unit ("1 can" -> canned)."""
    text = parsed.food
    if parsed.unit == "can" and "canned" not in text:
        text += " canned"
    return text
