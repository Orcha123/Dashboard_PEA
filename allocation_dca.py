"""
DCA guidé par une allocation cible : calcul de l'achat du mois (module sans Streamlit).

Principe : l'utilisateur fixe la part que chaque ligne devrait représenter dans son portefeuille. Chaque mois,
l'enveloppe va d'abord aux lignes les plus en retard sur leur cible, en actions entières, sans jamais rien vendre.
Le calcul n'utilise aucune prévision : c'est l'application arithmétique des poids choisis par l'utilisateur.
"""


def normaliser_poids(poids_par_nom):
    """Poids positifs ramenés à un total de 100 % ({} si aucun poids n'est positif)."""
    positifs = {nom: float(p) for nom, p in poids_par_nom.items() if p is not None and float(p) > 0}
    total = sum(positifs.values())
    return {nom: p * 100.0 / total for nom, p in positifs.items()} if total > 0 else {}


def ecart_a_la_cible(lignes, cle_valeur):
    """
    Part du portefeuille mal placée par rapport à la cible, en % : moitié de la somme des écarts absolus entre poids
    actuels et poids cibles (0 % = exactement sur la cible). None si le portefeuille est vide.
    """
    total = sum(l[cle_valeur] for l in lignes)
    if total <= 0:
        return None
    return sum(abs(l[cle_valeur] / total * 100.0 - l["poids_cible"]) for l in lignes) / 2.0


def calculer_achat_du_mois(lignes, budget):
    """
    lignes : liste de dictionnaires avec au moins
        "nom", "poids_cible" (toute unité positive, ramenée à 100 %), "valeur_eur" (valeur détenue, en €),
        "prix_eur" (cours d'une action en €, None si inconnu : la ligne n'est alors pas achetée).
      Les autres clés sont recopiées telles quelles dans le résultat.
    budget : enveloppe du mois, en €.

    Méthode :
    1. Valeur visée après l'apport = poids cible x (valeur des lignes + enveloppe).
    2. Montant idéal (en euros, fractionnaire) : enveloppe répartie au prorata de ce qui manque à chaque ligne.
    3. Achat en actions entières, une à une : à chaque pas, celle qui rapproche le plus le portefeuille de sa cible
       (réduction de la somme des carrés des écarts), tant que l'enveloppe le permet et qu'un achat ne l'en éloigne
       pas. Ce qui reste est gardé en liquidités pour le mois suivant.

    Renvoie {"lignes": [...], "investi": €, "reste": €, "ecart_avant": %, "ecart_apres": %}. Chaque ligne reçoit
    poids_cible (normalisé), poids_actuel, valeur_visee, montant_ideal, qte, cout_eur, poids_apres et
    trop_chere (une action coûte plus que l'enveloppe alors que la ligne est en retard sur sa cible).
    """
    budget = max(0.0, float(budget or 0.0))
    poids = normaliser_poids({l["nom"]: l.get("poids_cible", 0.0) for l in lignes})
    resultat = []
    for l in lignes:
        ligne = dict(l)
        ligne["poids_cible"] = poids.get(l["nom"], 0.0)
        ligne["valeur_eur"] = max(0.0, float(l.get("valeur_eur") or 0.0))
        prix = l.get("prix_eur")
        ligne["prix_eur"] = float(prix) if prix is not None and float(prix) > 0 else None
        resultat.append(ligne)

    valeur_lignes = sum(l["valeur_eur"] for l in resultat)
    total_vise = valeur_lignes + budget
    for l in resultat:
        l["poids_actuel"] = (l["valeur_eur"] / valeur_lignes * 100.0) if valeur_lignes > 0 else 0.0
        l["valeur_visee"] = l["poids_cible"] / 100.0 * total_vise
        l["qte"] = 0
        l["cout_eur"] = 0.0

    manques = [max(0.0, l["valeur_visee"] - l["valeur_eur"]) for l in resultat]
    somme_manques = sum(manques)
    for l, manque in zip(resultat, manques):
        l["montant_ideal"] = budget * manque / somme_manques if somme_manques > 0 else 0.0

    reste = budget
    if poids:
        while True:
            # Une action n'est achetée que si elle ne l'éloigne pas de sa cible : il lui manque au moins la moitié de
            # son prix. Une ligne ne dépasse donc jamais sa cible de plus d'une demi-action.
            meilleur, meilleur_gain = None, None
            for l in resultat:
                prix = l["prix_eur"]
                if prix is None or prix > reste + 1e-9:
                    continue
                ecart = l["valeur_visee"] - (l["valeur_eur"] + l["cout_eur"])
                gain = prix * (2.0 * ecart - prix)  # baisse de l'écart au carré si l'on achète une action de plus
                if gain >= -1e-6 and (meilleur_gain is None or gain > meilleur_gain):
                    meilleur, meilleur_gain = l, gain
            if meilleur is None:
                break
            meilleur["qte"] += 1
            meilleur["cout_eur"] += meilleur["prix_eur"]
            reste -= meilleur["prix_eur"]

    valeur_apres = sum(l["valeur_eur"] + l["cout_eur"] for l in resultat)
    for l in resultat:
        l["poids_apres"] = ((l["valeur_eur"] + l["cout_eur"]) / valeur_apres * 100.0) if valeur_apres > 0 else 0.0
        l["valeur_apres"] = l["valeur_eur"] + l["cout_eur"]
        l["trop_chere"] = bool(l["prix_eur"] is not None and l["prix_eur"] > budget and l["montant_ideal"] > 0 and l["qte"] == 0)

    return {
        "lignes": resultat,
        "investi": budget - reste,
        "reste": reste,
        "ecart_avant": ecart_a_la_cible(resultat, "valeur_eur"),
        "ecart_apres": ecart_a_la_cible(resultat, "valeur_apres"),
    }
