"""Calculs du suivi de poids : tableau des pesées, effet par dose, export Excel.

Une ligne de saisie = une date : injection ou non (et sa dose), poids mesuré, commentaire.
La perte entre deux pesées est attribuée à la dernière injection faite AVANT la seconde pesée.
Exemple : injection de 2,5 mg le 15.11 à 105 kg, puis injection le 22.11 à 102 kg
-> les -3 kg sont attribués à la dose du 15.11.
"""
from __future__ import annotations

import io

import pandas as pd

COLONNES = ["date", "injection", "dose_mg", "poids_kg", "commentaire"]


def vide() -> pd.DataFrame:
    return normaliser(pd.DataFrame(columns=COLONNES))


def _bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "oui", "vrai", "yes")
    return bool(v) if pd.notna(v) else False


def normaliser(df: pd.DataFrame) -> pd.DataFrame:
    """Types propres, une seule ligne par date, tri par date."""
    d = df.copy()
    if "injection" not in d.columns:  # anciens fichiers : injection = une dose était saisie
        d["injection"] = pd.to_numeric(d.get("dose_mg"), errors="coerce").notna() if len(d) else []
    for c in COLONNES:
        if c not in d.columns:
            d[c] = None
    d = d[COLONNES]
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["injection"] = d["injection"].map(_bool).astype(bool)
    d["dose_mg"] = pd.to_numeric(d["dose_mg"], errors="coerce").astype(float)
    d.loc[~d["injection"], "dose_mg"] = float("nan")
    d["poids_kg"] = pd.to_numeric(d["poids_kg"], errors="coerce").astype(float)
    d["commentaire"] = d["commentaire"].fillna("").astype(str).str.strip()
    d = d.dropna(subset=["date"])
    d = d[d["injection"] | d["poids_kg"].notna() | (d["commentaire"] != "")]
    d = d.drop_duplicates("date", keep="last")
    return d.sort_values("date").reset_index(drop=True)


def semaine_id(date) -> str:
    y, w, _ = pd.Timestamp(date).isocalendar()
    return f"{y}-S{w:02d}"


def upsert(df: pd.DataFrame, date, injection: bool, dose, poids, commentaire: str) -> pd.DataFrame:
    """Ajoute la saisie du jour `date`, ou remplace celle qui existe déjà ce jour-là."""
    d = normaliser(df)
    d = d[d["date"] != pd.Timestamp(date)]
    ligne = pd.DataFrame([{"date": pd.Timestamp(date), "injection": bool(injection),
                           "dose_mg": dose if injection else None, "poids_kg": poids,
                           "commentaire": commentaire or ""}])
    return normaliser(pd.concat([x for x in (d, ligne) if not x.empty], ignore_index=True))


def supprimer(df: pd.DataFrame, date) -> pd.DataFrame:
    d = normaliser(df)
    return d[d["date"] != pd.Timestamp(date)].reset_index(drop=True)


def tableau_hebdo(df: pd.DataFrame) -> pd.DataFrame:
    """Variation de poids entre deux pesées successives, ramenée à 7 jours,
    et dose de la dernière injection faite avant la pesée (celle qui a « agi »)."""
    d = normaliser(df)
    d["semaine"] = d["date"].apply(semaine_id)
    cols = ["jours", "variation_kg", "variation_kg_sem", "dose_attribuee", "date_injection", "cumul_kg",
            "cumul_pct"]
    p = d[d["poids_kg"].notna()].copy()
    if p.empty:
        for c in cols:
            d[c] = pd.NA
        return d
    p["jours"] = p["date"].diff().dt.days
    p["variation_kg"] = p["poids_kg"].diff()
    p["variation_kg_sem"] = p["variation_kg"] / (p["jours"] / 7)
    inj = d.loc[d["injection"], ["date", "dose_mg"]]
    avant = [inj[inj["date"] < t] for t in p["date"]]
    p["dose_attribuee"] = [a["dose_mg"].iloc[-1] if not a.empty else float("nan") for a in avant]
    p["date_injection"] = [a["date"].iloc[-1] if not a.empty else pd.NaT for a in avant]
    p.loc[p["jours"].isna(), ["dose_attribuee", "date_injection"]] = [float("nan"), pd.NaT]
    depart = p["poids_kg"].iloc[0]
    p["cumul_kg"] = p["poids_kg"] - depart
    p["cumul_pct"] = p["cumul_kg"] / depart * 100
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


def export_excel(df: pd.DataFrame) -> bytes:
    h = tableau_hebdo(df)
    saisies = normaliser(df).assign(injection=lambda x: x["injection"].map({True: "oui", False: "non"}))
    saisies = saisies.rename(columns={"date": "Date", "injection": "Injection", "dose_mg": "Dose (mg)",
                                      "poids_kg": "Poids (kg)", "commentaire": "Commentaire"})
    hebdo = h[h["poids_kg"].notna()][[
        "semaine", "date", "poids_kg", "variation_kg", "jours", "variation_kg_sem", "dose_attribuee",
        "date_injection", "cumul_kg", "cumul_pct", "commentaire"]].rename(columns={
            "semaine": "Semaine", "date": "Date pesée", "poids_kg": "Poids (kg)",
            "variation_kg": "Variation (kg)", "jours": "Jours depuis pesée préc.",
            "variation_kg_sem": "Variation (kg/sem.)", "dose_attribuee": "Dose attribuée (mg)",
            "date_injection": "Injection attribuée du", "cumul_kg": "Cumul (kg)", "cumul_pct": "Cumul (%)",
            "commentaire": "Commentaire"})
    doses = par_dose(h).rename(columns={
        "dose_mg": "Dose (mg)", "semaines": "Semaines", "variation_kg_sem": "Variation moyenne (kg/sem.)",
        "variation_totale_kg": "Variation totale (kg)", "meilleure_semaine_kg": "Meilleure semaine (kg)",
        "pire_semaine_kg": "Moins bonne semaine (kg)"})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl", date_format="DD.MM.YYYY", datetime_format="DD.MM.YYYY") as xw:
        for nom, t in [("Saisies", saisies), ("Pesées", hebdo), ("Par dose", doses)]:
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
