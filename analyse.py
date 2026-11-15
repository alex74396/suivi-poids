"""Calculs du suivi de poids : tableau hebdomadaire, effet par dose, export Excel.

Une ligne de saisie = une semaine : date, dose injectée (mg), poids mesuré (kg), commentaire.
"""
from __future__ import annotations

import io

import pandas as pd

COLONNES = ["date", "dose_mg", "poids_kg", "commentaire"]


def vide() -> pd.DataFrame:
    return pd.DataFrame(columns=COLONNES)


def normaliser(df: pd.DataFrame) -> pd.DataFrame:
    """Types propres, lignes sans date retirées, une seule ligne par semaine, tri par date."""
    d = df.copy()
    for c in COLONNES:
        if c not in d.columns:
            d[c] = None
    d = d[COLONNES]
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["dose_mg"] = pd.to_numeric(d["dose_mg"], errors="coerce")
    d["poids_kg"] = pd.to_numeric(d["poids_kg"], errors="coerce")
    d["commentaire"] = d["commentaire"].fillna("").astype(str).str.strip()
    d = d.dropna(subset=["date"])
    d = d[d["dose_mg"].notna() | d["poids_kg"].notna() | (d["commentaire"] != "")]
    # une seule saisie par semaine ISO : la dernière gagne
    d["_sem"] = d["date"].apply(semaine_id)
    d = d.drop_duplicates("_sem", keep="last").drop(columns="_sem")
    return d.sort_values("date").reset_index(drop=True)


def semaine_id(date) -> str:
    y, w, _ = pd.Timestamp(date).isocalendar()
    return f"{y}-S{w:02d}"


def upsert(df: pd.DataFrame, date, dose, poids, commentaire: str) -> pd.DataFrame:
    """Ajoute la saisie de la semaine de `date`, ou remplace celle qui existe déjà."""
    d = normaliser(df)
    sem = semaine_id(date)
    d = d[d["date"].apply(semaine_id) != sem]
    ligne = pd.DataFrame([{"date": pd.Timestamp(date), "dose_mg": dose, "poids_kg": poids,
                           "commentaire": commentaire or ""}])
    return normaliser(pd.concat([d, ligne], ignore_index=True))


def supprimer_semaine(df: pd.DataFrame, date) -> pd.DataFrame:
    d = normaliser(df)
    return d[d["date"].apply(semaine_id) != semaine_id(date)].reset_index(drop=True)


def tableau_hebdo(df: pd.DataFrame, pesee_avant_injection: bool = True) -> pd.DataFrame:
    """Variation de poids entre deux pesées successives, ramenée à une semaine.

    La variation entre la pesée précédente et celle-ci est attribuée à une dose :
    - pesée avant l'injection (défaut) : la dose injectée la semaine précédente ;
    - pesée après l'injection : la dose injectée cette semaine.
    """
    d = normaliser(df)
    d["semaine"] = d["date"].apply(semaine_id)
    p = d[d["poids_kg"].notna()].copy()
    if p.empty:
        for c in ["jours", "variation_kg", "variation_kg_sem", "dose_attribuee", "cumul_kg", "cumul_pct"]:
            d[c] = pd.NA
        return d
    p["jours"] = p["date"].diff().dt.days
    p["variation_kg"] = p["poids_kg"].diff()
    p["variation_kg_sem"] = p["variation_kg"] / (p["jours"] / 7)
    if pesee_avant_injection:
        # dose de la dernière injection connue avant cette pesée
        doses = d[["date", "dose_mg"]].dropna()
        p["dose_attribuee"] = [
            doses.loc[doses["date"] < dt, "dose_mg"].iloc[-1] if (doses["date"] < dt).any() else pd.NA
            for dt in p["date"]
        ]
    else:
        p["dose_attribuee"] = p["dose_mg"]
    p.loc[p["jours"].isna(), "dose_attribuee"] = pd.NA
    depart = p["poids_kg"].iloc[0]
    p["cumul_kg"] = p["poids_kg"] - depart
    p["cumul_pct"] = p["cumul_kg"] / depart * 100
    cols = ["jours", "variation_kg", "variation_kg_sem", "dose_attribuee", "cumul_kg", "cumul_pct"]
    return d.join(p[cols])


def par_dose(hebdo: pd.DataFrame) -> pd.DataFrame:
    """Variation moyenne de poids par semaine, pour chaque dose (moyenne pondérée par la durée)."""
    h = hebdo.dropna(subset=["variation_kg", "dose_attribuee"])
    if h.empty:
        return pd.DataFrame(columns=["dose_mg", "semaines", "variation_kg_sem", "variation_totale_kg",
                                     "meilleure_semaine_kg", "pire_semaine_kg"])
    h = h.assign(semaines=h["jours"] / 7)
    g = h.groupby("dose_attribuee")
    res = pd.DataFrame({
        "semaines": g["semaines"].sum(),
        "variation_totale_kg": g["variation_kg"].sum(),
        "meilleure_semaine_kg": g["variation_kg_sem"].min(),
        "pire_semaine_kg": g["variation_kg_sem"].max(),
    })
    res["variation_kg_sem"] = res["variation_totale_kg"] / res["semaines"]
    res = res.reset_index().rename(columns={"dose_attribuee": "dose_mg"})
    return res[["dose_mg", "semaines", "variation_kg_sem", "variation_totale_kg",
                "meilleure_semaine_kg", "pire_semaine_kg"]].sort_values("dose_mg").reset_index(drop=True)


def export_excel(df: pd.DataFrame, pesee_avant_injection: bool = True) -> bytes:
    h = tableau_hebdo(df, pesee_avant_injection)
    saisies = normaliser(df).rename(columns={
        "date": "Date", "dose_mg": "Dose (mg)", "poids_kg": "Poids (kg)", "commentaire": "Commentaire"})
    hebdo = h[["semaine", "date", "dose_mg", "poids_kg", "variation_kg", "variation_kg_sem",
               "dose_attribuee", "cumul_kg", "cumul_pct", "commentaire"]].rename(columns={
        "semaine": "Semaine", "date": "Date", "dose_mg": "Dose (mg)", "poids_kg": "Poids (kg)",
        "variation_kg": "Variation (kg)", "variation_kg_sem": "Variation (kg/sem.)",
        "dose_attribuee": "Dose attribuée (mg)", "cumul_kg": "Cumul (kg)", "cumul_pct": "Cumul (%)",
        "commentaire": "Commentaire"})
    doses = par_dose(h).rename(columns={
        "dose_mg": "Dose (mg)", "semaines": "Semaines", "variation_kg_sem": "Variation moyenne (kg/sem.)",
        "variation_totale_kg": "Variation totale (kg)", "meilleure_semaine_kg": "Meilleure semaine (kg)",
        "pire_semaine_kg": "Moins bonne semaine (kg)"})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", date_format="DD.MM.YYYY", datetime_format="DD.MM.YYYY") as xw:
        for nom, t in [("Saisies", saisies), ("Suivi hebdo", hebdo), ("Par dose", doses)]:
            t.to_excel(xw, sheet_name=nom, index=False)
            ws = xw.sheets[nom]
            for col in ws.columns:
                largeur = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(12, largeur + 2), 50)
                for c in col[1:]:
                    if isinstance(c.value, float):
                        c.number_format = "0.00"
            ws.freeze_panes = "A2"
    return buf.getvalue()
