import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyse  # noqa: E402
import stockage  # noqa: E402


def donnees():
    # injections hebdomadaires le dimanche, pesée le même jour ; une pesée sans injection le mercredi 25.11
    return pd.DataFrame({
        "date": ["2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22", "2026-11-25", "2026-11-29",
                 "2026-12-13"],
        "injection": [True, True, True, True, False, True, True],
        "dose_mg": [2.5, 2.5, 5.0, 5.0, None, 5.0, 7.5],
        "poids_kg": [110.0, 108.0, 105.0, 102.0, 101.5, 101.0, 98.0],
        "commentaire": ["début", None, "", "", "pesée en milieu de semaine", "", "deux semaines"],
    })


def test_exemple_utilisateur():
    # 15.11 : injection à 105 kg ; 22.11 : injection à 102 kg -> -3 kg pour la dose du 15.11
    h = analyse.tableau_hebdo(donnees()).set_index("date")
    l = h.loc[pd.Timestamp("2026-11-22")]
    assert l["variation_kg"] == -3.0
    assert l["dose_attribuee"] == 5.0 and l["date_injection"] == pd.Timestamp("2026-11-15")
    # la pesée du 08.11 est attribuée à l'injection du 01.11, pas à celle du jour même
    assert h.loc[pd.Timestamp("2026-11-08"), "date_injection"] == pd.Timestamp("2026-11-01")


def test_pesee_sans_injection():
    h = analyse.tableau_hebdo(donnees()).set_index("date")
    mer = h.loc[pd.Timestamp("2026-11-25")]
    assert mer["variation_kg"] == pytest.approx(-0.5)
    assert mer["variation_kg_sem"] == pytest.approx(-0.5 / 3 * 7)
    assert mer["date_injection"] == pd.Timestamp("2026-11-22")
    # 25.11 -> 29.11 : toujours l'injection du 22.11
    assert h.loc[pd.Timestamp("2026-11-29"), "date_injection"] == pd.Timestamp("2026-11-22")


def test_par_dose():
    d = analyse.par_dose(analyse.tableau_hebdo(donnees())).set_index("dose_mg")
    # 2,5 mg : 01.11->08.11 (-2) et 08.11->15.11 (-3) -> -2,5 kg/sem.
    assert d.loc[2.5, "variation_kg_sem"] == pytest.approx(-2.5)
    # 5 mg : 15->22 (-3), 22->25 (-0,5), 25->29 (-0,5), 29.11->13.12 (-3 sur 2 sem.) -> -7 kg sur 4 sem.
    assert d.loc[5.0, "variation_kg_sem"] == pytest.approx(-7 / 4)
    assert d.loc[5.0, "semaines"] == pytest.approx(4)
    assert 7.5 not in d.index  # aucune pesée après l'injection de 7,5 mg


def test_upsert_par_date():
    d = analyse.upsert(donnees(), "2026-11-25", False, 3.0, 101.2, "modif")
    assert len(d) == 7
    l = d[d["date"] == pd.Timestamp("2026-11-25")].iloc[0]
    assert l["poids_kg"] == 101.2 and pd.isna(l["dose_mg"]) and not l["injection"]
    d = analyse.upsert(d, "2026-11-26", True, 5.0, None, "")  # même semaine, autre jour : nouvelle ligne
    assert len(d) == 8
    assert len(analyse.supprimer(d, "2026-11-26")) == 7


def test_ancien_format_sans_colonne_injection():
    d = analyse.normaliser(pd.DataFrame({"date": ["2026-11-01", "2026-11-04"], "dose_mg": [2.5, None],
                                         "poids_kg": [100, 99.5], "commentaire": ["", ""]}))
    assert d["injection"].tolist() == [True, False]


def test_stockage_local_et_export(tmp_path):
    s = stockage.StockageLocal(tmp_path / "x.csv")
    assert s.charger().empty
    s.modifier(lambda d: analyse.upsert(d, "2026-11-09", True, 5, 93.2, "Noël, repas; « copieux »"), "t")
    s.modifier(lambda d: analyse.upsert(d, "2026-11-12", False, None, 92.9, ""), "t")
    s.modifier(lambda d: analyse.upsert(d, "2026-11-16", True, 5, 92.4, ""), "t")
    d = s.charger()
    assert d["poids_kg"].tolist() == [93.2, 92.9, 92.4]
    assert d["injection"].tolist() == [True, False, True]
    assert d["commentaire"].iloc[0] == "Noël, repas; « copieux »"
    xl = pd.read_excel(io.BytesIO(analyse.export_excel(d)), sheet_name=None)
    assert set(xl) == {"Saisies", "Pesées", "Par dose"}
    assert xl["Par dose"]["Variation totale (kg)"].iloc[0] == pytest.approx(-0.8)


class FausseReponse:
    def __init__(self, code, j=None):
        self.status_code, self._j = code, j or {}

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FausseAPI:
    """Imite l'API « contents » de GitHub, avec un conflit au premier PUT."""
    def __init__(self):
        self.fichier, self.sha, self.puts, self.conflit = None, 0, 0, True
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if "/contents/" not in url:  # infos du dépôt
            return FausseReponse(200)
        if self.fichier is None:
            return FausseReponse(404)
        return FausseReponse(200, {"content": self.fichier, "sha": str(self.sha)})

    def put(self, url, json=None, timeout=None):
        self.puts += 1
        if self.conflit:
            self.conflit = False
            return FausseReponse(409)
        assert json.get("sha") == (str(self.sha) if self.fichier else None)
        self.fichier, self.sha = json["content"], self.sha + 1
        return FausseReponse(201)


def test_stockage_github_simule():
    s = stockage.StockageGitHub("jeton", "u/r")
    s.s = FausseAPI()
    assert s.charger().empty
    s.modifier(lambda d: analyse.upsert(d, "2026-11-09", True, 5, 93.2, "é"), "t")
    assert s.s.puts == 2  # conflit puis réussite
    s.modifier(lambda d: analyse.upsert(d, "2026-11-16", True, 5, 92.4, ""), "t")
    d = s.charger()
    assert d["poids_kg"].tolist() == [93.2, 92.4] and d["commentaire"].iloc[0] == "é"
