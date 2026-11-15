"""Suivi de poids – traitement hebdomadaire.

Lancer en local :  streamlit run app.py
Chaque semaine : date, dose injectée, poids mesuré et commentaire. Les données sont stockées
dans un dépôt GitHub privé (voir stockage.py) ou, en local, dans data/suivi_poids.csv.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analyse
import stockage

st.set_page_config(page_title="Suivi poids", page_icon="⚖️", layout="centered")

PLOT_CFG = {"displayModeBar": False, "scrollZoom": False}
BLEU, VERT, ROUGE, GRIS = "#1F4E79", "#2E8B57", "#C0392B", "#8C8C8C"
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def fr(x, dec: int = 1, signe: bool = False) -> str:
    if x is None or pd.isna(x):
        return "–"
    s = f"{x:+.{dec}f}" if signe else f"{x:.{dec}f}"
    return s.replace(".", ",").replace("-", "−")


def fr_date(d) -> str:
    return pd.Timestamp(d).strftime("%d.%m.%Y")


@st.cache_resource
def store():
    return stockage.depuis_secrets(st.secrets)


@st.cache_data(ttl=60, show_spinner="Chargement des données…")
def charger() -> pd.DataFrame:
    return store().charger()


def enregistrer(f, message: str) -> bool:
    try:
        with st.spinner("Enregistrement…"):
            store().modifier(f, message)
    except Exception as e:  # réseau, jeton expiré…
        st.error(f"L'enregistrement a échoué : {e}")
        return False
    charger.clear()
    return True


def mise_en_page(fig: go.Figure, hauteur: int = 340) -> go.Figure:
    fig.update_layout(height=hauteur, margin=dict(l=8, r=8, t=30, b=8), hovermode="x unified",
                      legend=dict(orientation="h", y=1.12, x=0), dragmode=False,
                      separators=", ")
    return fig


try:
    df = charger()
except Exception as e:  # jeton invalide, dépôt introuvable, réseau…
    st.title("⚖️ Suivi poids")
    st.error(f"Impossible de lire les données : {e}")
    st.caption("Réglage à corriger dans Streamlit Cloud › Manage app › Settings › Secrets.")
    st.stop()
avant = st.session_state.get("pesee_avant", True)
hebdo = analyse.tableau_hebdo(df, avant)
pesees = hebdo.dropna(subset=["poids_kg"])

st.title("⚖️ Suivi poids")

# --- résumé en une ligne (les chiffres détaillés sont dans l'onglet Évolution) ---
if not pesees.empty:
    dernier = pesees.iloc[-1]
    recents = pesees.dropna(subset=["variation_kg"]).tail(4)
    moy4 = recents["variation_kg"].sum() / (recents["jours"].sum() / 7) if not recents.empty else None
    st.markdown(f"**{fr(dernier['poids_kg'])} kg** le {fr_date(dernier['date'])} · "
                f"**{fr(dernier['cumul_kg'], signe=True)} kg** depuis le début")

t_saisie, t_evol, t_dose, t_hist = st.tabs(["✏️ Saisie", "📉 Évolution", "💉 Par dose", "📋 Historique"])

# =============================================================================
# Saisie de la semaine
# =============================================================================
with t_saisie:
    jour = st.date_input("Date de l'injection / pesée", value=dt.date.today(), format="DD.MM.YYYY")
    lundi = jour - dt.timedelta(days=jour.weekday())
    sem = analyse.semaine_id(jour)
    st.caption(f"Semaine {sem.split('-S')[1]} · du {JOURS[0]} {lundi:%d.%m} au {JOURS[6]} "
               f"{lundi + dt.timedelta(days=6):%d.%m.%Y}")

    existant = df[df["date"].apply(analyse.semaine_id) == sem] if not df.empty else df
    ligne = existant.iloc[-1] if not existant.empty else None
    if ligne is not None:
        st.info(f"Une saisie existe déjà pour cette semaine (le {fr_date(ligne['date'])}). "
                "Vous pouvez la modifier ci-dessous.")

    precedent = df[df["date"] < pd.Timestamp(lundi)]
    dose_def = (ligne["dose_mg"] if ligne is not None and pd.notna(ligne["dose_mg"])
                else precedent["dose_mg"].dropna().iloc[-1] if precedent["dose_mg"].notna().any() else 2.5)
    poids_def = (ligne["poids_kg"] if ligne is not None and pd.notna(ligne["poids_kg"])
                 else precedent["poids_kg"].dropna().iloc[-1] if precedent["poids_kg"].notna().any() else None)

    # la clé dépend de la semaine : les champs se pré-remplissent quand on change de semaine
    with st.form(f"saisie_{sem}", border=True):
        dose = st.number_input("Dose injectée (mg)", min_value=0.0, max_value=50.0, value=float(dose_def),
                               step=0.25, format="%.2f")
        poids = st.number_input("Poids mesuré (kg)", min_value=0.0, max_value=400.0,
                                value=float(poids_def) if poids_def is not None else None,
                                step=0.1, format="%.1f", placeholder="ex. 92,4")
        comm = st.text_area("Commentaire (optionnel)", value=ligne["commentaire"] if ligne is not None else "",
                            placeholder="ex. semaine de Noël, repas copieux, oubli d'injection…", height=80)
        ok = st.form_submit_button("💾 Enregistrer la semaine", type="primary", use_container_width=True)
    if ok:
        if enregistrer(lambda d: analyse.upsert(d, jour, dose, poids, comm),
                       f"Saisie {sem} : {dose} mg, {poids} kg"):
            st.session_state["flash"] = f"Semaine {sem.split('-S')[1]} enregistrée ✅"
            st.rerun()
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    if ligne is not None:
        with st.popover("🗑️ Supprimer cette semaine", use_container_width=True):
            st.write(f"Supprimer la saisie du {fr_date(ligne['date'])} ?")
            if st.button("Oui, supprimer", type="primary"):
                if enregistrer(lambda d: analyse.supprimer_semaine(d, jour), f"Suppression {sem}"):
                    st.session_state["flash"] = "Saisie supprimée."
                    st.rerun()

# =============================================================================
# Évolution dans le temps
# =============================================================================
with t_evol:
    if pesees.empty:
        st.info("Aucune pesée enregistrée pour l'instant.")
    else:
        def delta(x, dec=1, unite="kg"):  # signe ASCII : Streamlit en déduit la flèche
            return None if pd.isna(x) else f"{x:+.{dec}f} {unite}".replace(".", ",")
        c1, c2, c3 = st.columns(3)
        c1.metric("Poids actuel", f"{fr(dernier['poids_kg'])} kg", delta(dernier["variation_kg"]),
                  delta_color="inverse")
        c2.metric("Depuis le début", f"{fr(dernier['cumul_kg'], signe=True)} kg",
                  delta(dernier["cumul_pct"], 1, "%"), delta_color="inverse")
        c3.metric("Moyenne 4 sem.", f"{fr(moy4, 2, signe=True)} kg/sem.")
        fig = go.Figure()
        fig.add_scatter(x=pesees["date"], y=pesees["poids_kg"], mode="lines+markers", name="Poids (kg)",
                        line=dict(color=BLEU, width=3), marker=dict(size=7),
                        customdata=pesees[["dose_mg", "commentaire"]].fillna(""),
                        hovertemplate="%{y:.1f} kg · dose %{customdata[0]} mg<br>%{customdata[1]}<extra></extra>")
        doses = hebdo.dropna(subset=["dose_mg"])
        fig.add_scatter(x=doses["date"], y=doses["dose_mg"], mode="lines+markers", name="Dose (mg)",
                        line=dict(color=GRIS, width=1.5, shape="hv", dash="dot"), marker=dict(size=5),
                        yaxis="y2", hovertemplate="%{y} mg<extra></extra>")
        fig.update_layout(yaxis=dict(title="kg"),
                          yaxis2=dict(title="mg", overlaying="y", side="right", showgrid=False, rangemode="tozero"))
        fig.update_xaxes(tickformat="%d.%m")
        st.markdown("#### " + "Poids et dose")
        st.plotly_chart(mise_en_page(fig), use_container_width=True, config=PLOT_CFG)

        var = pesees.dropna(subset=["variation_kg_sem"])
        if not var.empty:
            st.markdown("#### " + "Variation semaine par semaine")
            fig2 = go.Figure(go.Bar(
                x=var["date"], y=var["variation_kg_sem"],
                marker_color=[VERT if v <= 0 else ROUGE for v in var["variation_kg_sem"]],
                customdata=var[["dose_attribuee", "commentaire"]].fillna(""),
                hovertemplate="%{y:+.2f} kg/sem. · dose %{customdata[0]} mg<br>%{customdata[1]}<extra></extra>"))
            fig2.update_xaxes(tickformat="%d.%m")
            fig2.update_yaxes(title="kg / semaine", zeroline=True, zerolinecolor="#999")
            st.plotly_chart(mise_en_page(fig2, 280), use_container_width=True, config=PLOT_CFG)
            st.caption("Vert : perte de poids · rouge : prise de poids. Si une semaine manque, "
                       "la variation est ramenée à une semaine.")

        st.markdown("#### " + "Tableau hebdomadaire")
        tab = hebdo.sort_values("date", ascending=False)
        st.dataframe(
            tab[["semaine", "date", "dose_mg", "poids_kg", "variation_kg_sem", "cumul_kg", "commentaire"]],
            hide_index=True, use_container_width=True,
            column_config={
                "semaine": "Semaine",
                "date": st.column_config.DateColumn("Date", format="DD.MM.YY"),
                "dose_mg": st.column_config.NumberColumn("Dose (mg)", format="%.2f"),
                "poids_kg": st.column_config.NumberColumn("Poids", format="%.1f"),
                "variation_kg_sem": st.column_config.NumberColumn("Var. / sem.", format="%+.2f"),
                "cumul_kg": st.column_config.NumberColumn("Cumul", format="%+.1f"),
                "commentaire": "Commentaire",
            })

# =============================================================================
# Effet de la dose
# =============================================================================
with t_dose:
    st.radio("La pesée est faite…", [True, False], key="pesee_avant", horizontal=True,
             format_func=lambda v: "avant l'injection" if v else "après l'injection")
    st.caption("Avant l'injection : la perte mesurée cette semaine est attribuée à la dose de la semaine "
               "précédente. Après l'injection : elle est attribuée à la dose de la semaine même.")
    pd_dose = analyse.par_dose(hebdo)
    if pd_dose.empty:
        st.info("Il faut au moins deux pesées (et une dose) pour mesurer l'effet d'une dose.")
    else:
        lab = [f"{fr(x, 2).rstrip('0').rstrip(',')} mg" for x in pd_dose["dose_mg"]]
        fig3 = go.Figure(go.Bar(
            x=lab, y=pd_dose["variation_kg_sem"],
            marker_color=[VERT if v <= 0 else ROUGE for v in pd_dose["variation_kg_sem"]],
            text=[f"{fr(v, 2, signe=True)} kg" for v in pd_dose["variation_kg_sem"]], textposition="outside",
            hovertemplate="%{x} : %{y:+.2f} kg/sem.<extra></extra>"))
        fig3.update_yaxes(title="kg / semaine (moyenne)", zeroline=True, zerolinecolor="#999")
        fig3.update_xaxes(type="category")
        st.markdown("#### " + "Variation moyenne par semaine, selon la dose")
        st.plotly_chart(mise_en_page(fig3, 320), use_container_width=True, config=PLOT_CFG)

        st.dataframe(pd_dose, hide_index=True, use_container_width=True, column_config={
            "dose_mg": st.column_config.NumberColumn("Dose (mg)", format="%.2f"),
            "semaines": st.column_config.NumberColumn("Semaines", format="%.0f"),
            "variation_kg_sem": st.column_config.NumberColumn("Moy. kg/sem.", format="%+.2f"),
            "variation_totale_kg": st.column_config.NumberColumn("Total kg", format="%+.1f"),
            "meilleure_semaine_kg": st.column_config.NumberColumn("Meilleure", format="%+.2f"),
            "pire_semaine_kg": st.column_config.NumberColumn("Moins bonne", format="%+.2f"),
        })

        pts = hebdo.dropna(subset=["variation_kg_sem", "dose_attribuee"])
        fig4 = go.Figure(go.Scatter(
            x=pts["dose_attribuee"], y=pts["variation_kg_sem"], mode="markers",
            marker=dict(size=10, color=BLEU, opacity=0.6),
            customdata=pts[["semaine", "commentaire"]].fillna(""),
            hovertemplate="%{customdata[0]} · %{x} mg : %{y:+.2f} kg<br>%{customdata[1]}<extra></extra>"))
        fig4.update_xaxes(title="Dose (mg)", tickvals=sorted(pts["dose_attribuee"].unique()))
        fig4.update_yaxes(title="kg / semaine", zeroline=True, zerolinecolor="#999")
        fig4.update_layout(hovermode="closest")
        st.markdown("#### " + "Chaque semaine, selon la dose")
        st.plotly_chart(mise_en_page(fig4, 300).update_layout(hovermode="closest"),
                        use_container_width=True, config=PLOT_CFG)
        st.caption("Moyenne pondérée par la durée entre deux pesées. Peu de semaines pour une dose = "
                   "résultat encore fragile ; les commentaires aident à repérer les semaines atypiques.")

# =============================================================================
# Historique : modification et export
# =============================================================================
with t_hist:
    st.download_button("📥 Exporter en Excel", data=analyse.export_excel(df, avant),
                       file_name=f"suivi_poids_{dt.date.today():%Y-%m-%d}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    st.write("Modifiez directement les cellules, ajoutez ou supprimez des lignes, puis enregistrez.")
    edite = st.data_editor(
        df.sort_values("date", ascending=False), num_rows="dynamic", hide_index=True,
        use_container_width=True, key="editeur",
        column_config={
            "date": st.column_config.DateColumn("Date", format="DD.MM.YYYY", required=True),
            "dose_mg": st.column_config.NumberColumn("Dose (mg)", min_value=0.0, step=0.25, format="%.2f"),
            "poids_kg": st.column_config.NumberColumn("Poids (kg)", min_value=0.0, step=0.1, format="%.1f"),
            "commentaire": st.column_config.TextColumn("Commentaire"),
        })
    if st.button("💾 Enregistrer les modifications", type="primary", use_container_width=True):
        nouveau = analyse.normaliser(edite)
        dates = pd.to_datetime(edite["date"], errors="coerce").dropna()
        if dates.apply(analyse.semaine_id).duplicated().any():
            st.warning("Deux lignes tombaient dans la même semaine : seule la dernière a été gardée.")
        if enregistrer(lambda _: nouveau, "Modification de l'historique"):
            st.session_state.pop("editeur", None)
            st.session_state["flash_hist"] = "Historique enregistré ✅"
            st.rerun()
    if "flash_hist" in st.session_state:
        st.success(st.session_state.pop("flash_hist"))
    st.caption(f"Données : {store().nom} · {len(df)} semaine(s) enregistrée(s).")
