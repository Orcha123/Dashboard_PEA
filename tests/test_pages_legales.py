"""Tests des pages légales (python -m pytest tests)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pages_legales as P  # noqa: E402


def test_identite_renseignee_et_echappee():
    identite = P.identite_editeur("Jean <Dupont> & Fils", "123 456 789 00012", "1 rue de la Bourse, Paris", "contact@exemple.fr")
    mentions = P.html_mentions_legales(identite)
    assert "Jean &lt;Dupont&gt; &amp; Fils" in mentions and "<Dupont>" not in mentions
    assert "SIRET : 123 456 789 00012" in mentions and 'href="mailto:contact@exemple.fr"' in mentions
    assert "1 rue de la Bourse, Paris" in P.html_confidentialite(identite)
    assert "contact@exemple.fr" in P.html_pied_de_page(identite)


def test_secrets_manquants_signales():
    identite = P.identite_editeur()
    mentions = P.html_mentions_legales(identite)
    assert "secret EDITEUR_NOM" in mentions and "secret EDITEUR_ADRESSE" in mentions and "secret CONTACT_EMAIL" in mentions
    assert "en cours d'immatriculation" in mentions


def test_mentions_obligatoires_presentes():
    identite = P.identite_editeur("Éditeur", "1", "Adresse", "a@b.fr")
    assert "Non-CIF" in P.html_avertissement_amf()
    assert "risque de perte en capital" in P.html_avertissement_amf()
    assert "L221-28" in P.html_retractation()
    assert "sans aucun engagement de durée" in P.html_cgv()
    confidentialite = P.html_confidentialite(identite)
    for mention in ("CNIL", "droit d'accès", "Stripe", "Supabase", "Data Privacy Framework", "Mon compte"):
        assert mention in confidentialite, mention
    assert "<b>Boursy</b>" in P.html_avertissement_amf() and "<b>Autre</b>" in P.html_avertissement_amf("Autre")
