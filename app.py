import streamlit as st
import json
import re
import os
import io
import subprocess
import platform
from datetime import datetime
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# --- Configuration ---
st.set_page_config(page_title="🛒 Liste de courses", page_icon="🛒", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECETTES_PATH = os.path.join(BASE_DIR, "recettes.json")
CATALOGUE_PATH = os.path.join(BASE_DIR, "catalogue.json")


# --- Chargement des données ---
@st.cache_data
def load_recettes():
    with open(RECETTES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["plats"]


@st.cache_data
def load_catalogue():
    with open(CATALOGUE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["rayons"]


# --- Utilitaires ---
def parse_quantity(nom: str):
    """Extrait le nom de base et la quantité d'un ingrédient.
    Ex: 'Carottes (450g)' → ('Carottes', 450, 'g')
        'Tomates (3)' → ('Tomates', 3, '')
        'Crème fraîche' → ('Crème fraîche', None, '')
    """
    match = re.match(r"^(.+?)\s*\((\d+)\s*(g|kg|ml|L|cl)?\)$", nom)
    if match:
        base = match.group(1).strip()
        qty = int(match.group(2))
        unit = match.group(3) or ""
        return base, qty, unit
    return nom.strip(), None, ""


def merge_ingredients(ingredients_list):
    """Fusionne les ingrédients en dédoublonnant et cumulant les quantités.
    Retourne un dict: {rayon: [(nom_affiché, nom_base), ...]}
    """
    # Clé: (nom_base_lower, rayon) → {rayon, nom_base, qty, unit}
    merged = {}
    for ing in ingredients_list:
        nom = ing["nom"]
        rayon = ing["rayon"]
        base, qty, unit = parse_quantity(nom)
        key = (base.lower(), rayon)

        if key in merged:
            if qty is not None and merged[key]["qty"] is not None:
                merged[key]["qty"] += qty
            elif qty is not None:
                merged[key]["qty"] = qty
                merged[key]["unit"] = unit
        else:
            merged[key] = {
                "rayon": rayon,
                "nom_base": base,
                "qty": qty,
                "unit": unit,
            }

    # Construire le résultat par rayon
    result = {}
    for key, data in merged.items():
        rayon = data["rayon"]
        if rayon not in result:
            result[rayon] = []
        if data["qty"] is not None:
            display = f"{data['nom_base']} ({data['qty']}{data['unit']})"
        else:
            display = data["nom_base"]
        result[rayon].append(display)

    return result


def get_recipe_ingredients(recettes, selected_names):
    """Récupère tous les ingrédients des recettes sélectionnées."""
    ingredients = []
    for recette in recettes:
        if recette["nom"] in selected_names:
            ingredients.extend(recette["ingredients"])
    return ingredients


def build_final_list(recipe_items_by_rayon, free_items_by_rayon):
    """Combine les ingrédients recettes et les articles libres, par rayon."""
    all_rayons = set(list(recipe_items_by_rayon.keys()) + list(free_items_by_rayon.keys()))

    # Ordre préféré des rayons
    rayon_order = [
        "BOULANGERIE",
        "LÉGUMES",
        "FRUITS",
        "AIL & FINES HERBES",
        "CHARCUTERIE",
        "TRAITEUR",
        "POISSONNERIE",
        "BOUCHERIE",
        "SURGELÉS",
        "FROMAGES",
        "YAOURTS",
        "PRODUITS LAITIERS",
        "ÉPICERIE SALÉE",
        "CUISINE DU MONDE",
        "ÉPICERIE SUCRÉE",
        "BOISSONS",
        "NOURRITURE BÉBÉ",
        "HYGIÈNE & DIVERS",
    ]

    final = {}
    for rayon in rayon_order:
        if rayon in all_rayons:
            items = set()
            items.update(recipe_items_by_rayon.get(rayon, []))
            items.update(free_items_by_rayon.get(rayon, []))
            if items:
                final[rayon] = sorted(items)

    # Rayons non listés dans l'ordre
    for rayon in sorted(all_rayons - set(rayon_order)):
        items = set()
        items.update(recipe_items_by_rayon.get(rayon, []))
        items.update(free_items_by_rayon.get(rayon, []))
        if items:
            final[rayon] = sorted(items)

    return final


def build_notion_content(final_list, selected_recipes):
    """Construit le contenu Markdown Notion avec des to-do items."""
    lines = []

    if selected_recipes:
        lines.append(f"🍽️ *{' • '.join(selected_recipes)}*")
        lines.append("")

    for rayon, items in final_list.items():
        lines.append(f"## {rayon}")
        for item in items:
            lines.append(f"- [ ] {item}")
        lines.append("")

    return "\n".join(lines)


def export_to_docx(final_list, selected_recipes):
    """Génère un fichier Word de la liste de courses."""
    doc = Document()

    # Styles
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    # Titre
    title = doc.add_heading("Liste de courses", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = RGBColor(0, 0, 0)

    # Date
    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_run = date_para.add_run(f"Semaine du {datetime.now().strftime('%d/%m/%Y')}")
    date_run.font.size = Pt(10)
    date_run.font.color.rgb = RGBColor(100, 100, 100)

    # Plats sélectionnés
    if selected_recipes:
        doc.add_paragraph()
        plats_para = doc.add_paragraph()
        plats_run = plats_para.add_run("Plats : ")
        plats_run.bold = True
        plats_run.font.size = Pt(10)
        plats_text = plats_para.add_run(" • ".join(selected_recipes))
        plats_text.font.size = Pt(10)
        plats_text.font.color.rgb = RGBColor(80, 80, 80)

    doc.add_paragraph()

    # Articles par rayon
    for rayon, items in final_list.items():
        heading = doc.add_heading(rayon, level=2)
        for run in heading.runs:
            run.font.color.rgb = RGBColor(46, 117, 182)
            run.font.size = Pt(13)

        for item in items:
            para = doc.add_paragraph(style="List Bullet")
            run = para.add_run(item)
            run.font.size = Pt(11)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


# --- Chargement ---
recettes = load_recettes()
catalogue = load_catalogue()

# --- Session state ---
if "checked_items" not in st.session_state:
    st.session_state.checked_items = set()


# --- Interface ---
st.title("🛒 Liste de courses")

tab_recettes, tab_catalogue, tab_liste = st.tabs(
    ["🍽️ Recettes", "🏪 Catalogue", "📋 Ma liste"]
)

# =====================
# ONGLET 1 : RECETTES
# =====================
with tab_recettes:
    st.header("Sélectionnez vos plats de la semaine")

    selected_recipes = []
    cols = st.columns(2)
    for i, recette in enumerate(recettes):
        with cols[i % 2]:
            ingredients_str = ", ".join(ing["nom"] for ing in recette["ingredients"])
            if st.checkbox(
                recette["nom"],
                key=f"recette_{i}",
                help=ingredients_str,
            ):
                selected_recipes.append(recette["nom"])

    if selected_recipes:
        st.divider()
        st.subheader("Ingrédients sélectionnés")
        recipe_ingredients = get_recipe_ingredients(recettes, selected_recipes)
        recipe_by_rayon = merge_ingredients(recipe_ingredients)

        for rayon, items in sorted(recipe_by_rayon.items()):
            st.markdown(f"**{rayon}**")
            for item in items:
                st.markdown(f"- {item}")
    else:
        recipe_by_rayon = {}

# =====================
# ONGLET 2 : CATALOGUE
# =====================
with tab_catalogue:
    st.header("Ajoutez des articles par rayon")

    free_items_by_rayon = {}

    for rayon in catalogue:
        with st.expander(f"🏷️ {rayon['nom']} ({len(rayon['articles'])} articles)"):
            selected_in_rayon = []
            for j, article in enumerate(rayon["articles"]):
                if st.checkbox(
                    article,
                    key=f"cat_{rayon['nom']}_{j}",
                ):
                    selected_in_rayon.append(article)

            if selected_in_rayon:
                free_items_by_rayon[rayon["nom"]] = selected_in_rayon

# =====================
# ONGLET 3 : MA LISTE
# =====================
with tab_liste:
    # Recalculer recipe_by_rayon (car les variables d'onglet ne persistent pas)
    selected_recipes_final = []
    for i, recette in enumerate(recettes):
        if st.session_state.get(f"recette_{i}", False):
            selected_recipes_final.append(recette["nom"])

    recipe_ingredients_final = get_recipe_ingredients(recettes, selected_recipes_final)
    recipe_by_rayon_final = merge_ingredients(recipe_ingredients_final)

    # Recalculer free_items
    free_items_final = {}
    for rayon in catalogue:
        items = []
        for j, article in enumerate(rayon["articles"]):
            if st.session_state.get(f"cat_{rayon['nom']}_{j}", False):
                items.append(article)
        if items:
            free_items_final[rayon["nom"]] = items

    final_list = build_final_list(recipe_by_rayon_final, free_items_final)

    if final_list:
        st.header("📋 Ma liste de courses")

        if selected_recipes_final:
            st.caption(f"🍽️ Plats : {' • '.join(selected_recipes_final)}")

        st.divider()

        # Compteur
        total = sum(len(items) for items in final_list.values())
        checked_count = len(
            [
                item
                for rayon, items in final_list.items()
                for item in items
                if f"check_{rayon}_{item}" in st.session_state.checked_items
            ]
        )
        st.progress(
            checked_count / total if total > 0 else 0,
            text=f"✅ {checked_count}/{total} articles",
        )

        # Liste avec cases à cocher
        for rayon, items in final_list.items():
            st.subheader(rayon)
            for item in items:
                check_key = f"check_{rayon}_{item}"
                checked = st.checkbox(
                    item,
                    key=check_key,
                    value=check_key in st.session_state.checked_items,
                )
                if checked:
                    st.session_state.checked_items.add(check_key)
                elif check_key in st.session_state.checked_items:
                    st.session_state.checked_items.discard(check_key)

        st.divider()

        # Boutons d'action
        col1, col2, col3 = st.columns(3)
        with col1:
            docx_buffer = export_to_docx(final_list, selected_recipes_final)
            st.download_button(
                label="📥 Exporter en Word",
                data=docx_buffer,
                file_name=f"Liste_courses_{datetime.now().strftime('%Y-%m-%d')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            notion_content = build_notion_content(final_list, selected_recipes_final)
            if st.button("📝 Envoyer vers Notion"):
                st.session_state.notion_export_content = notion_content
                st.session_state.notion_export_recipes = selected_recipes_final
                st.session_state.show_notion_export = True

            if st.session_state.get("show_notion_export", False):
                st.info("⏳ La page Notion va être créée par Claude. Copiez le contenu ci-dessous si besoin.")
                st.code(st.session_state.get("notion_export_content", ""), language="markdown")
        with col3:
            if st.button("🗑️ Réinitialiser les coches"):
                st.session_state.checked_items = set()
                st.rerun()
    else:
        st.info(
            "👈 Sélectionnez des recettes dans l'onglet **Recettes** "
            "ou ajoutez des articles depuis le **Catalogue** pour constituer votre liste."
        )
