import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyse  # noqa: E402
import stockage  # noqa: E402


def donnees():
    return pd.DataFrame({
        "date": ["2026-10-05", "2026-10-12", "2026-10-19", "2026-11-02", "2026-11-09"],
        "dose_mg": [2.5, 2.5, 5.0, 5.0, 5.0],
        "poids_kg": [100.0, 99.0, 98.0, 94.0, 93.0],
        "commentaire": ["début", None, "", "deux semaines", "Noël"],
    })


def test_hebdo_et_trou():
    h = analyse.tableau_hebdo(donnees())
    assert h["variation_kg"].tolist()[1:] == [-1.0, -1.0, -4.0, -1.0]
    # 14 jours entre le 19.10 et le 02.11 : -4 kg -> -2 kg/semaine
    assert h["variation_kg_sem"].iloc[3] == pytest.approx(-2.0)
    assert h["cumul_kg"].iloc[-1] == -7.0


def test_par_dose_avant_injection():
    d = analyse.par_dose(analyse.tableau_hebdo(donnees(), True)).set_index("dose_mg")
    # 2,5 mg : semaines 12.10 et 19.10 -> -2 kg sur 2 sem.
    assert d.loc[2.5, "variation_kg_sem"] == pytest.approx(-1.0)
    # 5 mg : -4 kg sur 2 sem. + -1 kg sur 1 sem. -> -5/3
    assert d.loc[5.0, "variation_kg_sem"] == pytest.approx(-5 / 3)


def test_par_dose_apres_injection():
    d = analyse.par_dose(analyse.tableau_hebdo(donnees(), False)).set_index("dose_mg")
    assert d.loc[2.5, "semaines"] == pytest.approx(1)
    assert d.loc[5.0, "variation_kg_sem"] == pytest.approx(-6 / 4)


def test_upsert_remplace_la_semaine():
    d = analyse.upsert(donnees(), "2026-11-11", 7.5, 92.0, "modif")  # même semaine que le 09.11
    assert len(d) == 5
    assert d.iloc[-1]["dose_mg"] == 7.5 and d.iloc[-1]["commentaire"] == "modif"
    d = analyse.upsert(d, "2026-11-16", 7.5, None, "")
    assert len(d) == 6 and pd.isna(d.iloc[-1]["poids_kg"])
    assert len(analyse.supprimer_semaine(d, "2026-11-20")) == 5


def test_stockage_local_et_export(tmp_path):
    s = stockage.StockageLocal(tmp_path / "x.csv")
    assert s.charger().empty
    s.modifier(lambda d: analyse.upsert(d, "2026-11-09", 5, 93.2, "Noël, repas; « copieux »"), "t")
    s.modifier(lambda d: analyse.upsert(d, "2026-11-16", 5, 92.4, ""), "t")
    d = s.charger()
    assert d["poids_kg"].tolist() == [93.2, 92.4]
    assert d["commentaire"].iloc[0] == "Noël, repas; « copieux »"
    xl = pd.read_excel(__import__("io").BytesIO(analyse.export_excel(d)), sheet_name=None)
    assert set(xl) == {"Saisies", "Suivi hebdo", "Par dose"}


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
    s.modifier(lambda d: analyse.upsert(d, "2026-11-09", 5, 93.2, "é"), "t")
    assert s.s.puts == 2  # conflit puis réussite
    s.modifier(lambda d: analyse.upsert(d, "2026-11-16", 5, 92.4, ""), "t")
    d = s.charger()
    assert d["poids_kg"].tolist() == [93.2, 92.4] and d["commentaire"].iloc[0] == "é"
