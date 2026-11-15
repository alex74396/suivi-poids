"""Stockage des saisies dans un fichier CSV.

- En ligne (Streamlit Cloud) : le CSV vit dans un dépôt GitHub privé et chaque enregistrement
  y crée un commit (historique complet, rien ne se perd au redémarrage de l'app).
  Configuration dans les secrets Streamlit :

      [github]
      token  = "github_pat_..."          # jeton à accès « Contents: read & write » sur le dépôt
      repo   = "utilisateur/suivi-poids-donnees"
      path   = "suivi_poids.csv"         # optionnel
      branch = "main"                    # optionnel

- En local (sans secrets) : fichier data/suivi_poids.csv à côté de l'app.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

import analyse

LOCAL = Path(__file__).parent / "data" / "suivi_poids.csv"


def _vers_csv(df: pd.DataFrame) -> str:
    d = analyse.normaliser(df)
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    return d.to_csv(index=False)


def _depuis_csv(texte: str) -> pd.DataFrame:
    if not texte.strip():
        return analyse.vide()
    return analyse.normaliser(pd.read_csv(io.StringIO(texte), dtype={"commentaire": str}))


class ErreurGitHub(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"{message} (code {code})")
        self.code = code


def _verifier(r) -> None:
    if r.status_code < 400:
        return
    if r.status_code == 401:
        msg = ("Jeton GitHub refusé : il est invalide, expiré ou mal recopié dans les Secrets "
               "(il doit commencer par github_pat_, entre guillemets, sans espace).")
    elif r.status_code == 403:
        msg = ("Jeton GitHub sans permission suffisante : il lui faut l'accès au dépôt de données "
               "avec « Contents : Read and write ».")
    else:
        msg = "Erreur GitHub inattendue."
    raise ErreurGitHub(r.status_code, msg)


class StockageLocal:
    nom = "fichier local"

    def __init__(self, chemin: Path = LOCAL):
        self.chemin = chemin

    def charger(self) -> pd.DataFrame:
        if not self.chemin.exists():
            return analyse.vide()
        return _depuis_csv(self.chemin.read_text(encoding="utf-8"))

    def modifier(self, f: Callable[[pd.DataFrame], pd.DataFrame], message: str) -> pd.DataFrame:
        df = f(self.charger())
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(_vers_csv(df), encoding="utf-8")
        return df


class StockageGitHub:
    nom = "GitHub"

    def __init__(self, token: str, repo: str, path: str = "suivi_poids.csv", branch: str = "main"):
        self.url = f"https://api.github.com/repos/{repo}/contents/{path}"
        self.branch = branch
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}",
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def _lire(self):
        r = self.s.get(self.url, params={"ref": self.branch}, timeout=15)
        if r.status_code == 404:
            if self.s.get(self.url.split("/contents/")[0], timeout=15).status_code == 404:
                raise ErreurGitHub(404, "Dépôt de données introuvable : vérifiez « repo » dans les Secrets "
                                        "et que le jeton a bien accès à ce dépôt.")
            return analyse.vide(), None
        _verifier(r)
        j = r.json()
        texte = base64.b64decode(j["content"]).decode("utf-8")
        return _depuis_csv(texte), j["sha"]

    def charger(self) -> pd.DataFrame:
        return self._lire()[0]

    def modifier(self, f: Callable[[pd.DataFrame], pd.DataFrame], message: str) -> pd.DataFrame:
        # relit la dernière version juste avant d'écrire ; réessaie si quelqu'un a écrit entre-temps
        for _ in range(3):
            actuel, sha = self._lire()
            df = f(actuel)
            corps = {"message": message, "branch": self.branch,
                     "content": base64.b64encode(_vers_csv(df).encode("utf-8")).decode("ascii")}
            if sha:
                corps["sha"] = sha
            r = self.s.put(self.url, json=corps, timeout=20)
            if r.status_code in (200, 201):
                return df
            if r.status_code not in (409, 422):
                _verifier(r)
        raise RuntimeError("Enregistrement impossible : les données ont changé pendant l'écriture. Réessayez.")


def depuis_secrets(secrets) -> StockageLocal | StockageGitHub:
    try:
        cfg = secrets.get("github") if secrets is not None else None
    except Exception:  # pas de fichier secrets.toml
        cfg = None
    if cfg and cfg.get("token") and cfg.get("repo"):
        return StockageGitHub(str(cfg["token"]).strip(), str(cfg["repo"]).strip().strip("/"),
                              str(cfg.get("path", "suivi_poids.csv")).strip(),
                              str(cfg.get("branch", "main")).strip())
    return StockageLocal()
