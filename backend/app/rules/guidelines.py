"""
Published limits and goals the recipe check compares against.

Every number here comes from a cited guideline (see the spec's "Hypertension
rules" and "Type 2 diabetes rules"). Nothing is individualized: users'
own targets come from their care team and are entered as custom values.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    url: str


NHLBI_DASH = Source("NHLBI DASH eating plan",
                    "https://www.nhlbi.nih.gov/education/dash-eating-plan")
ACC_AHA_2025 = Source("2025 ACC/AHA high blood pressure guideline",
                      "https://www.uspharmacist.com/article/acc-aha-hypertension-guideline-update")
NIH_POTASSIUM = Source("NIH Office of Dietary Supplements (2019 NASEM Adequate Intakes)",
                       "https://ods.od.nih.gov/factsheets/Potassium-HealthProfessional/")
ADA_2026 = Source("ADA Standards of Care in Diabetes 2026, Section 5",
                  "https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188")
FDA_DAILY_VALUE = Source("FDA Daily Value for added sugars",
                         "https://www.fda.gov/food/nutrition-facts-label/"
                         "daily-value-nutrition-and-supplement-facts-labels")
CDC_CARBS = Source("CDC carb counting", "https://www.cdc.gov/diabetes/healthy-eating/"
                   "carb-counting-manage-blood-sugar.html")
NIAAA_DRINK = Source("NIAAA standard drink (14 g alcohol)",
                     "https://www.niaaa.nih.gov/alcohols-effects-health/what-standard-drink")
FDA_ALLERGENS = Source("FDA major food allergens",
                       "https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/"
                       "food-allergies")
YOUR_PROVIDER = Source("Your care team's recommendation", "")

SODIUM_DEFAULT_MG = 2300
SODIUM_STRICT_MG = 1500
ADDED_SUGARS_FLAG_G = 50
POTASSIUM_GOAL_MG = {"male": 3400, "female": 2600}
FIBER_G_PER_1000_KCAL = 14
CARB_SERVING_G = 15
GRAMS_ALCOHOL_PER_DRINK = 14
ALCOHOL_DRINKS_PER_DAY = {"male": 2, "female": 1}
# When sex isn't given, the lower limit and the lower goal are used, so no one is
# told something fits when it wouldn't for them.
UNSPECIFIED_SEX = "female"

POTASSIUM_CAUTION = (
    "The potassium goal doesn't apply to people with kidney disease or taking ACE "
    "inhibitors, ARBs or potassium-sparing diuretics. Check with your care team."
)
INSULIN_ALCOHOL_NOTE = (
    "This recipe uses alcohol. If you take insulin or medicines that can cause low blood "
    "sugar, alcohol raises the risk of a low; ADA advises extra care (5.19)."
)
LABEL_REMINDER = "Always check product labels; recipes and brands vary."
ESTIMATE_NOTE = (
    "Nutrients and costs are estimates from USDA and BLS data. Results compare this recipe with "
    "published guidelines and aren't medical advice."
)
