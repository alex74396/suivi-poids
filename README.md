# Suivi poids – app Streamlit

Saisie hebdomadaire de la dose injectée, du poids et d'un commentaire, avec graphiques d'évolution,
effet moyen de chaque dose et export Excel. Pensée pour le téléphone.

- `app.py` : interface (onglets Saisie, Évolution, Par dose, Historique).
- `analyse.py` : calculs (variation hebdomadaire, moyenne par dose, export Excel).
- `stockage.py` : enregistrement du CSV dans un dépôt GitHub **privé** (en ligne) ou dans `data/` (en local).
- `tests/test_analyse.py` : tests des calculs et du stockage local.

```bash
streamlit run app.py          # lancer en local (données dans data/suivi_poids.csv)
python -m pytest tests        # vérifier les calculs
```

## Règles de calcul

- Une saisie par date, avec un interrupteur « Injection ce jour ». On peut se peser sans injection.
- Variation = écart entre deux pesées successives, ramené à 7 jours.
- Effet d'une dose = somme des variations ÷ nombre de semaines passées sous cette dose.
  La perte entre deux pesées est attribuée à la dernière injection faite **avant** la seconde pesée
  (ex. injection le 15.11 à 105 kg, injection le 22.11 à 102 kg → −3 kg pour la dose du 15.11).

## Mise en ligne (une seule fois)

1. **Dépôt des données (privé)** : sur github.com, créer `suivi-poids-donnees`, *Private*,
   en cochant « Add a README ».
2. **Dépôt de l'app** : créer `suivi-poids` (Public, vide) et y pousser ce dossier.
3. **Jeton** : GitHub › Settings › Developer settings › Fine-grained tokens › Generate new token.
   Accès au seul dépôt `suivi-poids-donnees`, permission *Contents : Read and write*,
   expiration la plus longue possible (noter la date pour le renouveler).
4. **Streamlit** : share.streamlit.io › Create app › dépôt `suivi-poids`, branche `main`, fichier `app.py`.
   Dans *Advanced settings › Secrets*, coller le contenu de `.streamlit/secrets.toml.example`
   avec le vrai jeton.
5. Ouvrir l'adresse sur le téléphone › Partager › « Sur l'écran d'accueil ».

Chaque enregistrement crée un commit dans `suivi-poids-donnees` : historique complet et
rien ne se perd quand Streamlit met l'app en veille.
