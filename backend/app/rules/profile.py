"""What a person tells the app about their needs. Nothing here is stored in version 1."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Condition = Literal["hypertension", "type2_diabetes"]
Diet = Literal["vegetarian", "vegan", "pescatarian", "no_beef", "halal", "kosher",
               "gluten_free", "dairy_free", "alcohol_free"]
Allergen = Literal["milk", "egg", "fish", "crustacean", "tree_nut", "peanut", "wheat", "soy",
                   "sesame"]


class Profile(BaseModel):
    conditions: set[Condition] = Field(default_factory=set)
    sex: Literal["male", "female"] | None = None

    # Sodium: 2,300 mg a day by default, 1,500 mg "strict", or a provider's number.
    sodium: Literal["default", "strict", "custom"] = "default"
    sodium_custom_mg: float | None = Field(default=None, gt=0)
    # Added sugars: flagged above 50 g a day, or above a provider's number.
    added_sugars_custom_g: float | None = Field(default=None, gt=0)
    # Carbohydrates: no default limit; only checked against the user's own target.
    carb_target_g_per_meal: float | None = Field(default=None, gt=0)
    takes_insulin: bool = False

    meals_per_day: int = Field(default=3, ge=1, le=8)
    # A snack gets a half, quarter or eighth of one meal's share.
    snack_fraction: Literal[1, 0.5, 0.25, 0.125] = 1

    # Budget per meal, in minor units of the currency (cents for USD).
    budget_minor_per_meal: int | None = Field(default=None, gt=0)
    currency: Literal["USD"] = "USD"
    # The user's own prices, per 100 g, by food code; they replace the estimate.
    price_overrides_minor_per_100g: dict[int, float] = Field(default_factory=dict)

    diets: set[Diet] = Field(default_factory=set)
    allergens: set[Allergen] = Field(default_factory=set)
    custom_exclusions: list[str] = Field(default_factory=list)
    # Halal/kosher: whether the person buys certified meat and products.
    buys_certified: bool = False

    @model_validator(mode="after")
    def custom_sodium_needs_a_value(self) -> "Profile":
        if self.sodium == "custom" and self.sodium_custom_mg is None:
            raise ValueError("sodium_custom_mg is required when sodium is 'custom'")
        return self

    @property
    def meal_share(self) -> float:
        """This recipe's share of a day: one meal, or a fraction of one for a snack."""
        return self.snack_fraction / self.meals_per_day
