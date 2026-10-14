"""
Database tables.

Two USDA sources share the food table:
  - FNDDS foods, keyed by their 8-digit FNDDS food code, which is also the key
    of the price data (PP-NAP) and the added-sugar data (FPED);
  - SR Legacy foods (plain recipe ingredients: flour, salt, raw chicken),
    keyed by their 6-digit FoodData Central id, so the two never collide.
Nutrient amounts are per 100 g of food.
"""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Food(Base):
    __tablename__ = "food"
    __table_args__ = (CheckConstraint("source IN ('fndds', 'sr_legacy')", name="food_source"),)

    food_code: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), server_default="fndds")
    # How many USDA survey recipes use this food as an ingredient (SR foods only);
    # the matcher uses it to prefer everyday variants.
    recipe_uses: Mapped[int] = mapped_column(Integer, server_default="0")

    nutrients: Mapped[list["FoodNutrient"]] = relationship(back_populates="food")
    portions: Mapped[list["FoodPortion"]] = relationship(back_populates="food")
    tags: Mapped[list["FoodTag"]] = relationship(back_populates="food")


class Nutrient(Base):
    __tablename__ = "nutrient"

    nutrient_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(16))


class FoodNutrient(Base):
    __tablename__ = "food_nutrient"

    food_code: Mapped[int] = mapped_column(ForeignKey("food.food_code"), primary_key=True)
    nutrient_id: Mapped[int] = mapped_column(ForeignKey("nutrient.nutrient_id"), primary_key=True)
    amount_per_100g: Mapped[Decimal] = mapped_column(Numeric(12, 4))

    food: Mapped[Food] = relationship(back_populates="nutrients")


class FoodPortion(Base):
    """Household measures, e.g. "1 cup, chopped" = 67 g. Used to turn recipe amounts into grams."""

    __tablename__ = "food_portion"

    portion_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    food_code: Mapped[int] = mapped_column(ForeignKey("food.food_code"), index=True)
    description: Mapped[str] = mapped_column(Text)
    gram_weight: Mapped[Decimal] = mapped_column(Numeric(10, 3))

    food: Mapped[Food] = relationship(back_populates="portions")


class FoodPrice(Base):
    """
    Price per 100 edible grams. Amounts are in minor units of the currency
    (cents for USD), kept as a decimal because unit prices need sub-cent precision.
    """

    __tablename__ = "food_price"

    food_code: Mapped[int] = mapped_column(ForeignKey("food.food_code"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    amount_minor_per_100g: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    source: Mapped[str] = mapped_column(Text)
    price_period: Mapped[str] = mapped_column(String(32))


class FoodTag(Base):
    """What a food contains, e.g. "meat", "pork", "dairy", "allergen:peanuts"."""

    __tablename__ = "food_tag"
    __table_args__ = (CheckConstraint("set_by IN ('rule', 'review')", name="food_tag_set_by"),)

    food_code: Mapped[int] = mapped_column(ForeignKey("food.food_code"), primary_key=True)
    tag: Mapped[str] = mapped_column(String(64), primary_key=True)
    set_by: Mapped[str] = mapped_column(String(16))

    food: Mapped[Food] = relationship(back_populates="tags")
