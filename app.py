from pathlib import Path
import re
import unicodedata
import warnings

import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
import plotly.express as px
from streamlit_folium import st_folium
from branca.colormap import LinearColormap

warnings.filterwarnings("ignore")

# =========================================================
# 1. CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="TRUTH | Éducation Burkina Faso",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

F_GEO = DATA_DIR / "Provinces_45.gpkg"
F_BESOINS = DATA_DIR / "Besoins_education_2030_QGIS_FINAL.csv"
F_OSM = DATA_DIR / "Etablissements_Education_Consolides.gpkg"
LAYER_GEO = "dissoudre_45_provinces"

# =========================================================
# 2. DESIGN
# =========================================================
st.markdown("""
<style>
.stApp { background:#F4F6F2; color:#202B25; }
header[data-testid="stHeader"] { background:transparent; }
[data-testid="stSidebar"] {
    background:linear-gradient(180deg,#103B2D 0%,#08291F 100%);
}
[data-testid="stSidebar"] * { color:white !important; }
[data-testid="stSidebar"] label { font-weight:600; }
.block-container {
    padding-top:1.4rem; padding-bottom:2rem; max-width:1500px;
}
.truth-header {
    background:linear-gradient(105deg,#103B2D,#23704F);
    padding:25px 30px; border-radius:15px; margin-bottom:22px;
    color:white;
}
.truth-header h1 {
    color:white; font-size:38px; font-weight:800;
    letter-spacing:3px; margin:0;
}
.truth-header p { color:#E7F0E9; font-size:15px; margin:5px 0 0 0; }
.section-title {
    color:#164B36; font-size:24px; font-weight:750;
    margin:12px 0 15px 0;
}
.kpi-card {
    min-height:145px; padding:20px; border-radius:14px;
    color:white; box-shadow:0 4px 12px rgba(0,0,0,.10);
    margin-bottom:12px;
}
.kpi-label { font-size:14px; font-weight:650; margin-bottom:12px; }
.kpi-value {
    font-size:32px; font-weight:850; line-height:1.2;
    overflow-wrap:anywhere;
}
.kpi-note { font-size:12px; margin-top:8px; opacity:.92; }
.info-box {
    background:#FFF9E8; border-left:5px solid #D6A63B;
    padding:14px 17px; border-radius:7px; margin:15px 0;
    color:#403B2E;
}
[data-testid="stMetric"] {
    background:white; border:1px solid #E0E7E1;
    border-radius:12px; padding:15px;
}
[data-testid="stMetricValue"] { color:#174B37; font-weight:800; }
.stButton button { border-radius:8px; }
footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 3. FONCTIONS UTILITAIRES
# =========================================================
def normaliser(valeur):
    if pd.isna(valeur):
        return ""
    texte = str(valeur).strip().upper()
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^A-Z0-9]", "", texte)
    alias = {
        "KOURITENGA": "KOURITTENGA",
        "KOMANDJARI": "KOMONDJARI",
        "BALE": "LESBALE",
        "LESBALE": "LESBALE"
    }
    return alias.get(texte, texte)


def trouver_colonne(df, candidats):
    for nom in candidats:
        if nom in df.columns:
            return nom
    colonnes = {str(c).strip().lower(): c for c in df.columns}
    for nom in candidats:
        if nom.strip().lower() in colonnes:
            return colonnes[nom.strip().lower()]
    # Recherche souple : utile si QGIS a ajouté un préfixe au champ
    for nom in candidats:
        cible = nom.strip().lower()
        correspondances = [c for c in df.columns if str(c).strip().lower().endswith(cible)]
        if len(correspondances) == 1:
            return correspondances[0]
    return None


def serie_numerique(df, colonne):
    if colonne is None:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return pd.to_numeric(df[colonne], errors="coerce")


def nombre(valeur):
    if pd.isna(valeur):
        return "—"
    return f"{float(valeur):,.0f}".replace(",", " ")


def somme_disponible(serie):
    valeurs = pd.to_numeric(serie, errors="coerce")
    return valeurs.sum(min_count=1)


def kpi(titre, valeur, couleur, note=""):
    st.markdown(f"""
    <div class="kpi-card" style="background:{couleur};">
      <div class="kpi-label">{titre}</div>
      <div class="kpi-value">{valeur}</div>
      <div class="kpi-note">{note}</div>
    </div>
    """, unsafe_allow_html=True)


def note_methodologique(texte):
    st.markdown(f'<div class="info-box">{texte}</div>', unsafe_allow_html=True)


def titre_section(texte):
    st.markdown(
        f'<div class="section-title">{texte}</div>',
        unsafe_allow_html=True
    )


def verifier_indicateurs(mapping):
    manquants = [libelle for libelle, colonne in mapping.items() if colonne is None]
    if manquants:
        st.warning(
            "Certains champs n'ont pas été retrouvés dans les fichiers : "
            + ", ".join(manquants)
            + ". Les indicateurs concernés apparaîtront comme indisponibles."
        )


# =========================================================
# 4. CHARGEMENT DES PROVINCES
# =========================================================
@st.cache_data(show_spinner="Chargement des provinces...")
def charger_provinces(chemin, couche):
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier absent : {chemin}")
    gdf = gpd.read_file(chemin, layer=couche)
    if not isinstance(gdf, gpd.GeoDataFrame) or "geometry" not in gdf:
        raise ValueError("Le fichier des provinces ne contient pas de géométrie.")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    col_province = trouver_colonne(
        gdf, ["BFA_admin_Code_adm2_name_old", "Province"]
    )
    col_region = trouver_colonne(
        gdf, [
            "Education_45_provinces_codes_Region",
            "Region", "adm1_name"
        ]
    )
    if col_province is None:
        raise ValueError(
            "Champ du nom des provinces introuvable dans Provinces_45.gpkg."
        )

    gdf["PROVINCE_APP"] = gdf[col_province].fillna("Non renseignée").astype(str)
    gdf["REGION_APP"] = (
        gdf[col_region].fillna("Non renseignée").astype(str)
        if col_region else "Non renseignée"
    )
    gdf["CLE_APP"] = gdf["PROVINCE_APP"].map(normaliser)
    return gdf


# =========================================================
# 5. CHARGEMENT DES BESOINS 2030
# =========================================================
@st.cache_data(show_spinner="Chargement des projections et besoins...")
def charger_besoins(chemin):
    if not chemin.exists():
        return pd.DataFrame()
    df = pd.read_csv(chemin, encoding="utf-8-sig")
    col_prov = trouver_colonne(df, ["Province"])
    if col_prov is None:
        raise ValueError("Le CSV des besoins ne contient pas le champ Province.")
    df["CLE_APP"] = df[col_prov].map(normaliser)
    return df


# =========================================================
# 6. CHARGEMENT OPENSTREETMAP
# =========================================================
@st.cache_data(show_spinner="Chargement des établissements...")
def charger_ecoles(chemin):
    if not chemin.exists():
        return None, None
    couches = gpd.list_layers(chemin)["name"].tolist()
    points = gpd.read_file(chemin, layer="Ecoles_Points") if "Ecoles_Points" in couches else None
    polygones = gpd.read_file(chemin, layer="Ecoles_Polygones") if "Ecoles_Polygones" in couches else None

    for couche in (points, polygones):
        if couche is not None:
            if couche.crs is None:
                couche.set_crs("EPSG:4326", inplace=True)
            else:
                couche.to_crs("EPSG:4326", inplace=True)
    return points, polygones


try:
    provinces = charger_provinces(F_GEO, LAYER_GEO)
    besoins = charger_besoins(F_BESOINS)
    ecoles_points, ecoles_polygones = charger_ecoles(F_OSM)

    if not besoins.empty:
        colonnes_a_ajouter = [
            c for c in besoins.columns
            if c not in provinces.columns and c not in ("Province", "CLE_APP")
        ]
        besoins_jointure = besoins[["CLE_APP"] + colonnes_a_ajouter].drop_duplicates("CLE_APP")
        provinces = provinces.merge(besoins_jointure, on="CLE_APP", how="left")
except Exception as erreur:
    st.error(f"Erreur de chargement des données : {erreur}")
    st.stop()


# =========================================================
# 7. IDENTIFICATION DES CHAMPS
# =========================================================
COL_ECOLES = trouver_colonne(provinces, [
    "Education_45_provinces_codes_Nb_Ecoles", "Nb_Ecoles"
])
COL_SALLES = trouver_colonne(provinces, [
    "Education_45_provinces_codes_Nb_Salles", "Nb_Salles"
])
COL_MAITRES = trouver_colonne(provinces, [
    "Education_45_provinces_codes_Nb_Maitres", "Nb_Maitres"
])
COL_ELEVES = trouver_colonne(provinces, [
    "Education_45_provinces_codes_Nb_Eleves", "Nb_Eleves"
])
COL_IP = trouver_colonne(provinces, [
    "Education_45_provinces_codes_Nouvel indice de pression (IP)",
    "Education_45_provinces_codes_Nouvel indice de   pression (IP)",
    "Nouvel indice de pression (IP)",
    "Nouvel indice de   pression (IP)"
])
COL_POP = trouver_colonne(provinces, ["Population_6_11", "Population_2030"])
COL_AUG = trouver_colonne(provinces, ["Augmentation_2020_2030"])
COL_DEF_SALLES = trouver_colonne(provinces, ["Deficit_Salles_2030"])
COL_DEF_MAITRES = trouver_colonne(provinces, ["Deficit_Enseignants_2030"])

verifier_indicateurs({
    "Nombre d'écoles": COL_ECOLES,
    "Nombre de salles": COL_SALLES,
    "Nombre d'enseignants": COL_MAITRES,
    "Nombre d'élèves": COL_ELEVES,
    "Indice de pression": COL_IP,
    "Population 2030": COL_POP,
    "Augmentation 2020–2030": COL_AUG,
    "Déficit en salles": COL_DEF_SALLES,
    "Déficit en enseignants": COL_DEF_MAITRES
})

provinces["ECOLES_APP"] = serie_numerique(provinces, COL_ECOLES)
provinces["SALLES_APP"] = serie_numerique(provinces, COL_SALLES)
provinces["MAITRES_APP"] = serie_numerique(provinces, COL_MAITRES)
provinces["ELEVES_APP"] = serie_numerique(provinces, COL_ELEVES)
provinces["IP_APP"] = serie_numerique(provinces, COL_IP)
provinces["POP2030_APP"] = serie_numerique(provinces, COL_POP)
provinces["AUG2030_APP"] = serie_numerique(provinces, COL_AUG)
provinces["DEF_SALLES_APP"] = serie_numerique(provinces, COL_DEF_SALLES)
provinces["DEF_MAITRES_APP"] = serie_numerique(provinces, COL_DEF_MAITRES)

# =========================================================
# 8. FILTRES ET NAVIGATION
# =========================================================
st.sidebar.markdown("# 🎓 TRUTH")
st.sidebar.markdown("**Planification scolaire intelligente**")
st.sidebar.markdown("---")

regions = sorted(provinces["REGION_APP"].dropna().unique().tolist())
choix_region = st.sidebar.selectbox(
    "Filtrer par région", ["Toutes les régions"] + regions
)

base_filtre = (
    provinces.copy() if choix_region == "Toutes les régions"
    else provinces[provinces["REGION_APP"] == choix_region].copy()
)
liste_provinces = sorted(base_filtre["PROVINCE_APP"].dropna().unique().tolist())
choix_province = st.sidebar.selectbox(
    "Filtrer par province", ["Toutes les provinces"] + liste_provinces
)
donnees = (
    base_filtre.copy() if choix_province == "Toutes les provinces"
    else base_filtre[base_filtre["PROVINCE_APP"] == choix_province].copy()
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Navigation")
page = st.sidebar.radio(
    "Choisir une rubrique",
    [
        "Tableau de bord",
        "Pression éducative actuelle",
        "Population scolaire 2030",
        "Besoins en salles et enseignants",
        "Établissements scolaires",
        "Données provinciales"
    ],
    label_visibility="collapsed"
)
st.sidebar.markdown("---")
st.sidebar.caption("Data Challenge Burkina Faso 2026\n\nDéfi 3")


# =========================================================
# 9. CARTE THÉMATIQUE DES PROVINCES
# =========================================================
def afficher_carte(gdf, champ, titre, cle):
    if champ not in gdf.columns:
        st.error(f"Indicateur indisponible : {champ}")
        return
    carte_df = gdf[gdf.geometry.notna()].copy()
    carte_df[champ] = pd.to_numeric(carte_df[champ], errors="coerce")
    valeurs = carte_df[champ].dropna()
    if valeurs.empty:
        st.warning(f"Aucune valeur numérique disponible pour : {titre}")
        return

    # Conserver les valeurs manquantes comme manquantes (gris), pas comme zéro.
    carte_df["VALEUR_CARTE"] = carte_df[champ]
    carte_df["geometry"] = carte_df.geometry.simplify(
        0.0008, preserve_topology=True
    )
    affichage = carte_df[
        ["PROVINCE_APP", "REGION_APP", "VALEUR_CARTE", "geometry"]
    ].copy()

    centre = carte_df.geometry.union_all().centroid
    carte = folium.Map(
        location=[centre.y, centre.x],
        zoom_start=6,
        tiles="OpenStreetMap",
        control_scale=True
    )

    minimum, maximum = float(valeurs.min()), float(valeurs.max())
    if minimum == maximum:
        maximum = minimum + 1
    couleurs = LinearColormap(
        ["#FFF4D6", "#F6C65B", "#E68A35", "#C64E32", "#762B35"],
        vmin=minimum, vmax=maximum
    )

    def style(feature):
        valeur = feature["properties"].get("VALEUR_CARTE")
        try:
            couleur = couleurs(float(valeur)) if valeur is not None else "#D9DED9"
        except (TypeError, ValueError):
            couleur = "#D9DED9"
        return {
            "fillColor": couleur, "color": "#FFFFFF",
            "weight": 1.2, "fillOpacity": 0.85
        }

    folium.GeoJson(
        affichage.to_json(drop_id=True),
        name=titre,
        style_function=style,
        highlight_function=lambda feature: {
            "color": "#102F25", "weight": 3, "fillOpacity": 0.95
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["PROVINCE_APP", "REGION_APP", "VALEUR_CARTE"],
            aliases=["Province :", "Région :", titre + " :"],
            localize=True, sticky=True
        )
    ).add_to(carte)

    couleurs.caption = titre
    couleurs.add_to(carte)
    folium.LayerControl(collapsed=True).add_to(carte)

    st_folium(
        carte, key=f"truth_map_{cle}",
        use_container_width=True, height=650,
        returned_objects=[]
    )


def graphique_classement(df, champ, titre, couleur="YlOrRd", top=None):
    tableau = df[["PROVINCE_APP", champ]].copy()
    tableau[champ] = pd.to_numeric(tableau[champ], errors="coerce")
    tableau = tableau.dropna().sort_values(champ, ascending=False)
    if top:
        tableau = tableau.head(top)
    if tableau.empty:
        st.info(f"Pas de données disponibles pour {titre}.")
        return
    tableau = tableau.sort_values(champ, ascending=True)
    fig = px.bar(
        tableau, x=champ, y="PROVINCE_APP",
        orientation="h", color=champ,
        color_continuous_scale=couleur,
        labels={champ: titre, "PROVINCE_APP": "Province"}
    )
    fig.update_layout(
        height=max(420, min(850, 28 * len(tableau) + 120)),
        yaxis={"categoryorder": "total ascending"},
        paper_bgcolor="#F4F6F2",
        plot_bgcolor="#F4F6F2",
        coloraxis_showscale=False,
        margin=dict(l=10, r=30, t=20, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)


# =========================================================
# 10. EN-TÊTE GÉNÉRAL
# =========================================================
st.markdown("""
<div class="truth-header">
  <h1>TRUTH</h1>
  <p>Plateforme intelligente d'aide à la planification scolaire</p>
  <p>BURKINA FASO · DATA CHALLENGE 2026 · DÉFI 3</p>
</div>
""", unsafe_allow_html=True)


# =========================================================
# 11. TABLEAU DE BORD
# =========================================================
if page == "Tableau de bord":
    titre_section("Vue stratégique de l’éducation")
    st.write(
        "Une lecture territoriale de la pression éducative, de la demande "
        "scolaire projetée et des besoins indicatifs à l'horizon 2030."
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi("PROVINCES ANALYSÉES", nombre(len(donnees)),
            "linear-gradient(135deg,#164B36,#287B53)", "Périmètre sélectionné")
    with c2:
        kpi("ÉLÈVES ACTUELS", nombre(somme_disponible(donnees["ELEVES_APP"])),
            "linear-gradient(135deg,#1D5685,#287DB5)", "Statistiques 2023–2024")
    with c3:
        kpi("DÉFICIT INDICATIF EN SALLES",
            nombre(somme_disponible(donnees["DEF_SALLES_APP"])),
            "linear-gradient(135deg,#A75B16,#D58B2D)", "Estimation à l'horizon 2030")
    with c4:
        kpi("DÉFICIT INDICATIF EN ENSEIGNANTS",
            nombre(somme_disponible(donnees["DEF_MAITRES_APP"])),
            "linear-gradient(135deg,#872F3C,#BD4A52)", "Estimation à l'horizon 2030")

    st.markdown("### Pression éducative par province")
    afficher_carte(donnees, "IP_APP", "Indice de pression éducative", "dashboard_pressure")

    st.markdown("### Les dix provinces les plus sous pression")
    graphique_classement(donnees, "IP_APP", "Indice de pression", top=10)


# =========================================================
# 12. PRESSION ÉDUCATIVE ACTUELLE
# =========================================================
elif page == "Pression éducative actuelle":
    titre_section("Pression éducative actuelle · 2023–2024")
    a, b, c = st.columns(3)
    with a:
        kpi("ÉCOLES", nombre(somme_disponible(donnees["ECOLES_APP"])),
            "linear-gradient(135deg,#164B36,#287B53)")
    with b:
        kpi("SALLES DE CLASSE", nombre(somme_disponible(donnees["SALLES_APP"])),
            "linear-gradient(135deg,#1D5685,#287DB5)")
    with c:
        kpi("ENSEIGNANTS", nombre(somme_disponible(donnees["MAITRES_APP"])),
            "linear-gradient(135deg,#805020,#C58A36)")

    afficher_carte(donnees, "IP_APP", "Indice de pression éducative", "current_pressure")
    graphique_classement(donnees, "IP_APP", "Indice de pression")


# =========================================================
# 13. POPULATION SCOLAIRE 2030
# =========================================================
elif page == "Population scolaire 2030":
    titre_section("Demande démographique à l'horizon 2030")
    a, b = st.columns(2)
    with a:
        kpi("POPULATION 6–11 ANS EN 2030",
            nombre(somme_disponible(donnees["POP2030_APP"])),
            "linear-gradient(135deg,#164B36,#287B53)", "Population projetée")
    with b:
        kpi("AUGMENTATION 2020–2030",
            nombre(somme_disponible(donnees["AUG2030_APP"])),
            "linear-gradient(135deg,#1D5685,#287DB5)", "Évolution projetée")

    afficher_carte(
        donnees, "AUG2030_APP",
        "Augmentation de la population scolaire 2020–2030",
        "population_2030"
    )
    graphique_classement(
        donnees, "AUG2030_APP", "Augmentation projetée",
        couleur="YlGn"
    )
    note_methodologique(
        "<b>Attention :</b> la population de 6 à 11 ans est une projection "
        "démographique de l'INSD. Elle ne correspond pas automatiquement "
        "aux effectifs effectivement inscrits à l'école."
    )


# =========================================================
# 14. BESOINS EN SALLES ET ENSEIGNANTS
# =========================================================
elif page == "Besoins en salles et enseignants":
    titre_section("Besoins indicatifs à l'horizon 2030")
    a, b = st.columns(2)
    with a:
        kpi("DÉFICIT EN SALLES",
            nombre(somme_disponible(donnees["DEF_SALLES_APP"])),
            "linear-gradient(135deg,#A75B16,#D58B2D)",
            "Hypothèse : 50 enfants par salle")
    with b:
        kpi("DÉFICIT EN ENSEIGNANTS",
            nombre(somme_disponible(donnees["DEF_MAITRES_APP"])),
            "linear-gradient(135deg,#872F3C,#BD4A52)",
            "Hypothèse : 50 enfants par enseignant")

    choix = st.radio(
        "Choisir l'indicateur",
        ["Déficit en salles", "Déficit en enseignants"],
        horizontal=True
    )
    if choix == "Déficit en salles":
        champ = "DEF_SALLES_APP"
        titre = "Déficit indicatif en salles de classe"
        cle = "needs_rooms"
    else:
        champ = "DEF_MAITRES_APP"
        titre = "Déficit indicatif en enseignants"
        cle = "needs_teachers"

    afficher_carte(donnees, champ, titre, cle)
    graphique_classement(donnees, champ, "Déficit estimé", couleur="OrRd")
    note_methodologique(
        "<b>Hypothèses de calcul :</b> 50 enfants par salle et 50 enfants "
        "par enseignant, avec une couverture théorique de 100 % de la "
        "population projetée de 6 à 11 ans. Ces résultats sont indicatifs "
        "et ne constituent pas des besoins officiels validés."
    )


# =========================================================
# 15. ÉTABLISSEMENTS SCOLAIRES OPENSTREETMAP
# =========================================================
elif page == "Établissements scolaires":
    titre_section("Établissements scolaires représentés dans OpenStreetMap")

    if ecoles_points is None and ecoles_polygones is None:
        st.warning(
            "Les couches Ecoles_Points et Ecoles_Polygones "
            "n'ont pas été trouvées dans le GeoPackage."
        )
    else:
        # Filtrage régional/provincial si les champs existent dans OSM.
        pts = ecoles_points.copy() if ecoles_points is not None else None
        polys = ecoles_polygones.copy() if ecoles_polygones is not None else None

        for couche in (pts, polys):
            if couche is not None and not couche.empty:
                if "adm1_name" in couche.columns and choix_region != "Toutes les régions":
                    couche.drop(
                        couche[couche["adm1_name"] != choix_region].index,
                        inplace=True
                    )
                if "adm2_name" in couche.columns and choix_province != "Toutes les provinces":
                    cle_prov = normaliser(choix_province)
                    couche.drop(
                        couche[couche["adm2_name"].map(normaliser) != cle_prov].index,
                        inplace=True
                    )

        nb_points = len(pts) if pts is not None else 0
        nb_polygones = len(polys) if polys is not None else 0
        a, b = st.columns(2)
        with a:
            kpi("REPRÉSENTATIONS PONCTUELLES", nombre(nb_points),
                "linear-gradient(135deg,#1D5685,#287DB5)")
        with b:
            kpi("REPRÉSENTATIONS POLYGONAIRES", nombre(nb_polygones),
                "linear-gradient(135deg,#A75B16,#D58B2D)")

        carte = folium.Map(
            location=[12.2, -1.5], zoom_start=6,
            tiles="OpenStreetMap", control_scale=True
        )

        if polys is not None and not polys.empty:
            polys = polys[polys.geometry.notna()].copy()
            polys["geometry"] = polys.geometry.simplify(
                0.0005, preserve_topology=True
            )
            champs = [
                c for c in ["name", "amenity", "building", "operator_type"]
                if c in polys.columns
            ]
            affichage = polys[champs + ["geometry"]].copy()
            folium.GeoJson(
                affichage.to_json(drop_id=True),
                name="Établissements polygonaux",
                style_function=lambda feature: {
                    "fillColor": "#E49A45", "color": "#A75B16",
                    "weight": 1, "fillOpacity": 0.45
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=champs[:2],
                    aliases=["Nom :", "Type :"][:len(champs[:2])]
                ) if champs else None
            ).add_to(carte)

        if pts is not None and not pts.empty:
            pts = pts[pts.geometry.notna()].copy()
            if len(pts) > 5000:
                pts = pts.sample(5000, random_state=42)
            groupe = folium.FeatureGroup(
                name="Établissements ponctuels", show=True
            )
            for _, ligne in pts.iterrows():
                geom = ligne.geometry
                if geom is None or geom.is_empty or geom.geom_type != "Point":
                    continue
                nom = ligne.get("name", "Établissement sans nom")
                folium.CircleMarker(
                    location=[geom.y, geom.x],
                    radius=3, color="#174B83",
                    fill=True, fill_color="#287DB5",
                    fill_opacity=0.85, tooltip=str(nom)
                ).add_to(groupe)
            groupe.add_to(carte)

        folium.LayerControl(collapsed=False).add_to(carte)
        st_folium(
            carte, key="truth_map_osm",
            use_container_width=True, height=700,
            returned_objects=[]
        )
        note_methodologique(
            "<b>Limite des données :</b> OpenStreetMap est un inventaire "
            "collaboratif et non exhaustif. Les objets ponctuels et "
            "polygonaux sont des représentations distinctes et ne doivent "
            "pas être additionnés comme s'ils correspondaient forcément "
            "à des établissements différents."
        )


# =========================================================
# 16. DONNÉES PROVINCIALES
# =========================================================
elif page == "Données provinciales":
    titre_section("Tableau de données territoriales")
    tableau = donnees[[
        "PROVINCE_APP", "REGION_APP", "ECOLES_APP", "SALLES_APP",
        "MAITRES_APP", "ELEVES_APP", "IP_APP", "POP2030_APP",
        "AUG2030_APP", "DEF_SALLES_APP", "DEF_MAITRES_APP"
    ]].copy()

    tableau.columns = [
        "Province", "Région", "Écoles", "Salles actuelles",
        "Enseignants actuels", "Élèves actuels", "Indice de pression",
        "Population 6–11 ans en 2030", "Augmentation 2020–2030",
        "Déficit indicatif en salles", "Déficit indicatif en enseignants"
    ]

    st.dataframe(
        tableau, use_container_width=True,
        hide_index=True, height=650
    )
    st.download_button(
        "⬇ Télécharger les données affichées",
        data=tableau.to_csv(index=False).encode("utf-8-sig"),
        file_name="TRUTH_donnees_provinciales.csv",
        mime="text/csv"
    )


# =========================================================
# 17. PIED DE PAGE
# =========================================================
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#64736A; font-size:12px; padding:10px;">
  <b>TRUTH</b> · Data Challenge Burkina Faso 2026 — Défi 3<br>
  Sources : MENAPLN · INSD · OpenStreetMap · Limites administratives<br>
  Analyse et cartographie : 2026
</div>
""", unsafe_allow_html=True)
