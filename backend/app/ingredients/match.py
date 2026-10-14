"""
Match recipe food words to a USDA food description.

USDA survey foods are named "Head, qualifier, qualifier" ("Kale, raw";
"Beans, black, canned"). The ranking rewards descriptions whose words are
covered by the recipe text, especially the head, prefers plain ingredients over
prepared dishes, and prefers raw forms unless the recipe says otherwise.
Every score component is kept, so a match can be explained.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS = {"and", "or", "with", "of", "the", "a", "an", "in", "for", "to", "type",
             "style", "boneless", "skinless", "skin", "bone", "nfs", "ns", "as", "made",
             "from", "regular", "plain", "whole", "large", "medium", "small", "mix"}

# Words that mark a prepared dish or special product; penalized unless asked for.
DISH_WORDS = {"soup", "salad", "sandwich", "pie", "casserole", "baby", "infant", "toddler",
              "formula", "restaurant", "fast", "school", "dinner", "entree", "frozen",
              "meal", "kit", "puree", "pudding", "smoothie", "shake", "drink", "beverage",
              "sauce", "dip", "spread", "bar", "snack", "cereal", "candy", "dessert",
              "stew", "chowder", "burrito", "taco", "pizza", "burger", "roll", "dumpling"}

COOKING_WORDS = {"cooked", "boiled", "baked", "roasted", "fried", "grilled", "steamed",
                 "sauteed", "broiled", "stewed", "canned"}

# Recipe phrasing -> USDA phrasing. Applied to the recipe text before matching.
SYNONYMS = [
    (r"\ball[- ]purpose flour\b", "flour white all purpose"),
    (r"\bscallions?\b", "green onion"),
    (r"\bspring onions?\b", "green onion"),
    (r"\bgarbanzo beans?\b", "chickpea"),
    (r"\b(?:confectioners'?|powdered|icing) sugar\b", "sugar powdered"),
    (r"\bgranulated sugar\b", "sugar white granulated"),
    (r"\bbell peppers?\b", "pepper sweet"),
    (r"\bheavy (?:whipping )?cream\b", "cream heavy"),
    (r"\bhalf[- ]and[- ]half\b", "cream half and half"),
    (r"\bextra[- ]virgin olive oil\b|\bevoo\b", "olive oil"),
    (r"\bcilantro\b", "cilantro coriander"),
    (r"\bzucchini\b", "zucchini squash summer"),
    (r"\bground beef\b", "beef ground"),
    (r"\bground turkey\b", "turkey ground"),
    (r"\bkosher salt\b|\bsea salt\b|\btable salt\b", "salt table"),
    (r"\bblack pepper\b", "pepper black"),
    (r"\bbaking soda\b", "baking soda sodium bicarbonate"),
    (r"\bcornstarch\b", "corn starch"),
    (r"\bsoy sauce\b", "soy sauce"),
    (r"\bparmesan\b", "cheese parmesan"),
    (r"\bcheddar\b", "cheese cheddar"),
    (r"\bmozzarella\b", "cheese mozzarella"),
    (r"\bfeta\b", "cheese feta"),
    (r"\bgreek yogurt\b", "yogurt greek"),
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


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [_singular(w) for w in words if w not in STOPWORDS]


def apply_synonyms(text: str) -> str:
    text = text.lower()
    for pattern, replacement in SYNONYMS:
        text = re.sub(pattern, replacement, text)
    return text


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
    def __init__(self, foods: list[tuple[int, str]]):
        self.foods = foods
        self.food_tokens = [tokens(desc) for _, desc in foods]
        self.head_tokens = [tokens(desc.split(",")[0]) for _, desc in foods]
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

        results = []
        for i in pool:
            ftoks = set(self.food_tokens[i])
            matched = qset & ftoks
            coverage = sum(self.idf.get(t, 1.0) for t in matched) / q_weight
            head = set(self.head_tokens[i])
            head_match = len(head & qset) / len(head) if head else 0.0
            extra = ftoks - qset - {"raw"} - COOKING_WORDS
            penalties = []
            score = coverage + 0.6 * head_match - 0.04 * len(extra)

            dish = (ftoks & DISH_WORDS) - qset
            if dish:
                score -= 0.35
                penalties.append(f"dish/product word: {', '.join(sorted(dish))}")
            if "raw" in ftoks and not wants_cooked:
                score += 0.12
            if wants_cooked and "raw" in ftoks:
                score -= 0.2
                penalties.append("raw, but recipe says cooked")

            results.append(Candidate(
                food_code=self.foods[i][0], description=self.foods[i][1],
                score=round(score, 4), coverage=round(coverage, 3),
                head_match=round(head_match, 3), extra_words=len(extra), penalties=penalties,
            ))

        results.sort(key=lambda c: (-c.score, len(c.description)))
        return results[:limit]
