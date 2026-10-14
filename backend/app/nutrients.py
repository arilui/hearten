"""
Nutrient keys used across the app.

The nutrient table is keyed by USDA's legacy nutrient numbers (as FNDDS uses
them), plus two FPED values stored under ids far above USDA's own.
"""

ENERGY_KCAL = 208
CARBOHYDRATE_G = 205
FIBER_G = 291
TOTAL_SUGARS_G = 269
SODIUM_MG = 307
POTASSIUM_MG = 306
ALCOHOL_G = 221

ADDED_SUGARS_G = 900001      # from FPED (FNDDS foods) or a rule (SR Legacy foods)
ALCOHOLIC_DRINKS = 900002    # from FPED, FNDDS foods only

# Nutrients the recipe check reads.
CHECKED = (ENERGY_KCAL, CARBOHYDRATE_G, FIBER_G, SODIUM_MG, POTASSIUM_MG, ALCOHOL_G,
           ADDED_SUGARS_G)
