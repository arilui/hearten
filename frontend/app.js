"use strict";

const API = window.HEARTEN_API || "";
const STORE_KEY = "hearten:v1";

const EXAMPLE = [
  "1 lb boneless skinless chicken breasts, cut into strips",
  "2 tbsp soy sauce",
  "1 tbsp honey",
  "2 tbsp canola oil",
  "2 cloves garlic, minced",
  "1 tbsp fresh ginger, grated",
  "1 red bell pepper, sliced",
  "2 cups chopped broccoli",
  "1 medium carrot, sliced",
  "1 cup long-grain white rice",
].join("\n");

const STATUS_LABEL = {
  fits: "Fits", over: "Over a meal's share", incomplete: "Missing data", info: "",
  meets_goal: "Meets goal", below_goal: "Below goal", progress: "Toward goal",
  doesnt_fit: "Doesn't fit", check: "Check",
};

const form = document.getElementById("check-form");
const results = document.getElementById("results");
const formError = document.getElementById("form-error");
const submit = document.getElementById("submit");

// ------------------------------------------------------------ small helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function number(value) {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fmtAmount(value, unit) {
  if (value === null || value === undefined) return "";
  const digits = unit === "mg" || value >= 100 ? 0 : 1;
  return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })} ${unit}`;
}

function dollars(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

// ---------------------------------------------------------------- the form

function readProfile() {
  const data = new FormData(form);
  const all = (name) => data.getAll(name).map(String);
  const budget = number(data.get("budget"));
  const exclude = String(data.get("exclude") || "")
    .split(",").map((s) => s.trim()).filter(Boolean);
  const sodium = String(data.get("sodium") || "default");
  return {
    conditions: all("condition"),
    sex: data.get("sex") || null,
    sodium,
    sodium_custom_mg: sodium === "custom" ? number(data.get("sodium_custom_mg")) : null,
    added_sugars_custom_g: number(data.get("added_sugars_custom_g")),
    carb_target_g_per_meal: number(data.get("carb_target_g_per_meal")),
    takes_insulin: data.get("takes_insulin") !== null,
    meals_per_day: number(data.get("meals_per_day")) || 3,
    snack_fraction: number(data.get("snack_fraction")) || 1,
    budget_minor_per_meal: budget ? Math.round(budget * 100) : null,
    diets: all("diet"),
    allergens: all("allergen"),
    custom_exclusions: exclude,
    buys_certified: data.get("buys_certified") !== null,
  };
}

function updateVisibility() {
  const data = new FormData(form);
  const conditions = data.getAll("condition");
  const diets = data.getAll("diet");
  const shown = {
    "any-condition": conditions.length > 0,
    diabetes: conditions.includes("type2_diabetes"),
    "sodium-custom": data.get("sodium") === "custom",
    certified: diets.includes("halal") || diets.includes("kosher"),
  };
  for (const node of form.querySelectorAll("[data-when]")) {
    node.hidden = !shown[node.dataset.when];
  }
}

// Settings live in this browser only, as a convenience; nothing is sent anywhere
// except with a check request.
function saveForm() {
  try {
    const data = {};
    for (const field of form.elements) {
      if (!field.name) continue;
      if (field.type === "checkbox" || field.type === "radio") {
        data[`${field.name}=${field.value}`] = field.checked;
      } else {
        data[field.name] = field.value;
      }
    }
    localStorage.setItem(STORE_KEY, JSON.stringify(data));
  } catch { /* storage unavailable: settings just won't be remembered */ }
}

function restoreForm() {
  let data = null;
  try { data = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch { data = null; }
  if (!data) return;
  for (const field of form.elements) {
    if (!field.name) continue;
    if (field.type === "checkbox" || field.type === "radio") {
      const key = `${field.name}=${field.value}`;
      if (key in data) field.checked = Boolean(data[key]);
    } else if (field.name in data) {
      field.value = data[field.name];
    }
  }
}

function validate(recipe, servings, profile) {
  if (!recipe.trim()) return "Paste at least one ingredient line.";
  if (!servings || servings < 1) return "Enter how many servings the recipe makes.";
  if (profile.sodium === "custom" && !profile.sodium_custom_mg) {
    return "Enter your care team's daily sodium limit, or choose a standard limit.";
  }
  return null;
}

function errorDetail(body) {
  if (!body || !body.detail) return null;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
  return null;
}

async function onSubmit(event) {
  event.preventDefault();
  const recipe = form.elements.recipe.value;
  const servings = number(form.elements.servings.value);
  const profile = readProfile();
  const problem = validate(recipe, servings, profile);
  formError.hidden = !problem;
  formError.textContent = problem || "";
  if (problem) return;

  saveForm();
  submit.setAttribute("aria-busy", "true");
  submit.textContent = "Checking…";
  results.replaceChildren(el("p", { class: "loading", text: "Matching ingredients and checking your plan…" }));

  try {
    const response = await fetch(`${API}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe, servings, profile }),
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(errorDetail(body) || `The check didn't run (error ${response.status}).`);
    }
    render(body);
  } catch (error) {
    const message = error instanceof TypeError
      ? "Couldn't reach the Hearten service. Check your connection and try again."
      : error.message;
    results.replaceChildren(el("div", { class: "verdict over" },
      el("p", { class: "verdict-text", text: "The check didn't run." }),
      el("p", { class: "verdict-sub", text: message })));
  } finally {
    submit.removeAttribute("aria-busy");
    submit.textContent = "Check this recipe";
  }
}

// ----------------------------------------------------------------- results

function render(data) {
  const { result, ingredients } = data;
  const notes = annotations(result);

  const verdictClass = result.fits_plan === true ? "fits" : result.fits_plan === false ? "over" : "check";
  const servingsText = `Per serving, for ${result.servings} serving${result.servings === 1 ? "" : "s"}.`;
  const verdict = el("div", { class: `verdict ${verdictClass}` },
    el("p", { class: "verdict-text", text: result.summary }),
    el("p", { class: "verdict-sub", text: servingsText }));

  const recipeCard = el("section", { class: "panel annotated", "aria-labelledby": "matched-heading" },
    el("h2", { id: "matched-heading", text: "Your recipe, matched" }),
    el("ol", {}, ingredients.map((ing) => {
      const lineNotes = notes.get(ing.line) || [];
      const matched = ing.food_code !== null;
      return el("li", { class: matched ? "" : "unmatched" },
        el("span", { class: "line", text: ing.line }),
        el("div", { class: "margin" },
          matched
            ? el("p", {}, el("span", { class: "grams", text: ing.grams === null ? "amount not counted" : `${ing.grams} g` }), ` of ${ing.food}`)
            : el("p", { text: "Couldn't identify this food, so it wasn't counted." }),
          ing.warnings.filter((w) => w !== "couldn't identify the food").map((w) => el("p", { text: w })),
          lineNotes.map((n) => el("p", { class: "flagnote", text: n }))));
    })));

  const nutrients = el("section", { class: "group", "aria-labelledby": "nutrients-heading" },
    el("h2", { id: "nutrients-heading", text: "Nutrients per serving" }),
    result.nutrients.map(nutrientRow));

  const budget = budgetSection(result.budget);
  const diet = result.diet.length ? dietSection(result.diet) : null;

  const footnotes = el("ul", { class: "notes-list" }, result.notes.map((n) => el("li", { text: n })));

  const wrap = el("div", { class: "results-in" },
    verdict, nutrients, budget, diet, recipeCard, footnotes);
  results.replaceChildren(el("h2", { id: "results-heading", class: "visually-hidden", text: "Results" }), wrap);
  if (window.matchMedia("(max-width: 880px)").matches) {
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// Notes to show beside each recipe line: what it's behind, and what's missing.
function annotations(result) {
  const notes = new Map();
  const add = (line, text) => {
    if (!notes.has(line)) notes.set(line, []);
    if (!notes.get(line).includes(text)) notes.get(line).push(text);
  };
  for (const check of result.nutrients) {
    if (check.status === "over" && check.contributors.length) {
      add(check.contributors[0].line, `Most of the ${check.label.toLowerCase()}`);
    }
  }
  if (result.budget.status === "over" && result.budget.most_expensive.length) {
    add(result.budget.most_expensive[0].line, "Most of the cost");
  }
  for (const d of result.diet) {
    for (const c of d.conflicts) add(c.line, `${d.requirement}: ${c.reason}`);
    for (const c of d.to_check) add(c.line, c.reason);
  }
  for (const n of result.not_counted) {
    if (n.reason !== "couldn't identify the food") add(n.line, `Not counted: ${n.reason}`);
  }
  return notes;
}

function statusChip(status, label) {
  const text = label ?? STATUS_LABEL[status];
  return text ? el("span", { class: `status ${status}`, text }) : null;
}

function nutrientRow(check) {
  const node = document.getElementById("tpl-check").content.firstElementChild.cloneNode(true);
  node.querySelector(".check-label").textContent = check.label;
  const label = check.key === "carbohydrate" && check.status === "over" ? "Over your target" : undefined;
  const chip = statusChip(check.status, label);
  if (chip) node.querySelector(".check-top").append(chip);
  node.querySelector(".check-message").textContent = check.message;

  const meter = node.querySelector(".meter");
  if (check.kind === "limit" && check.meal_share) {
    const track = Math.max(check.per_serving, check.meal_share) * 1.15;
    meter.hidden = false;
    meter.classList.toggle("over", check.status === "over");
    meter.querySelector(".meter-fill").style.width = `${(check.per_serving / track) * 100}%`;
    meter.querySelector(".meter-mark").style.left = `${(check.meal_share / track) * 100}%`;
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label",
      `${fmtAmount(check.per_serving, check.unit)} against a meal's share of ${fmtAmount(check.meal_share, check.unit)}`);
  } else if (check.kind === "goal" && check.percent_of_day !== null) {
    meter.hidden = false;
    meter.querySelector(".meter-mark").remove();
    meter.querySelector(".meter-fill").style.width = `${Math.min(check.percent_of_day, 1) * 100}%`;
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `${Math.round(check.percent_of_day * 100)}% of the daily goal`);
  }

  const detail = node.querySelector(".check-detail");
  const parts = [];
  if (check.status === "over" || check.status === "incomplete") {
    const top = check.contributors.slice(0, 2).map((c) => c.line);
    if (top.length) parts.push(`Most from: ${top.join("; ")}.`);
  }
  if (check.missing_data.length) parts.push(`No data for: ${check.missing_data.join("; ")}.`);
  if (parts.length) { detail.hidden = false; detail.textContent = parts.join(" "); }

  if (check.notes.length) {
    const list = node.querySelector(".check-notes");
    list.hidden = false;
    list.append(...check.notes.map((n) => el("li", { text: n })));
  }
  if (check.source && check.kind !== "info") {
    const source = node.querySelector(".check-source");
    source.hidden = false;
    source.append("Source: ", check.source.url
      ? el("a", { href: check.source.url, target: "_blank", rel: "noopener", text: check.source.name })
      : check.source.name);
  }
  return node;
}

function budgetSection(budget) {
  const row = el("article", { class: "check-row" },
    el("div", { class: "check-top" },
      el("h3", { class: "check-label", text: "Cost per serving" }),
      statusChip(budget.status, budget.status === "over" ? "Over budget" : undefined)),
    el("p", { class: "check-message", text: budget.message }));
  if (budget.most_expensive.length) {
    row.append(el("p", { class: "check-detail",
      text: "Most expensive: " + budget.most_expensive
        .map((c) => `${c.line} (${dollars(c.amount)})`).join("; ") + "." }));
  }
  if (budget.missing_prices.length) {
    row.append(el("p", { class: "check-detail", text: `No price estimate for: ${budget.missing_prices.join("; ")}.` }));
  }
  return el("section", { class: "group", "aria-labelledby": "budget-heading" },
    el("h2", { id: "budget-heading", text: "Budget" }), row);
}

function dietSection(diet) {
  return el("section", { class: "group", "aria-labelledby": "diet-heading" },
    el("h2", { id: "diet-heading", text: "What you eat" }),
    diet.map((d) => el("article", { class: "check-row" },
      el("div", { class: "check-top" },
        el("h3", { class: "check-label", text: d.requirement }),
        statusChip(d.status)),
      el("p", { class: "check-message", text: d.message }),
      d.conflicts.length ? el("ul", { class: "check-notes" },
        d.conflicts.map((c) => el("li", { text: `${c.line}: ${c.reason}` }))) : null,
      d.to_check.length ? el("ul", { class: "check-notes" },
        d.to_check.map((c) => el("li", { text: `${c.line}: ${c.reason}` }))) : null,
      d.cant_know ? el("p", { class: "check-detail", text: `Can't be known from a recipe: ${d.cant_know}` }) : null)));
}

// -------------------------------------------------------------------- theme

const themeToggle = document.getElementById("theme-toggle");
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function currentTheme() {
  return document.documentElement.dataset.theme || (systemDark.matches ? "dark" : "light");
}

// The button names the theme it switches to.
function paintToggle() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  themeToggle.querySelector("span").textContent = next === "dark" ? "Dark mode" : "Light mode";
  themeToggle.querySelector(".icon-moon").style.display = next === "dark" ? "" : "none";
  themeToggle.querySelector(".icon-sun").style.display = next === "light" ? "" : "none";
  themeToggle.setAttribute("aria-label", `Switch to ${next} mode`);
}

themeToggle.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("hearten:theme", next); } catch { /* not remembered */ }
  paintToggle();
});
systemDark.addEventListener("change", paintToggle);
paintToggle();

// ------------------------------------------------------------------- start

restoreForm();
updateVisibility();
form.addEventListener("change", () => { updateVisibility(); saveForm(); });
form.addEventListener("submit", onSubmit);
document.getElementById("example").addEventListener("click", () => {
  form.elements.recipe.value = EXAMPLE;
  form.elements.servings.value = 4;
  form.elements.recipe.focus();
});
