"""Tests de l'envoi des e-mails (python -m pytest tests)."""
import email
import email.header
import os
import smtplib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import courriels as M  # noqa: E402


def test_rapport_d_alertes_echappe_les_noms():
    alertes = [{"Actif": "Air <Liquide> (EUR)", "Prix": "150,00 €", "Cible": "165,00 €", "Score": 72, "Motif": "Sous le Prix Cible 🎯"}]
    message = M.composer_email_alertes_radar("envoi@exemple.test", "moi@exemple.test", alertes, "https://boursy.example")
    sujet = str(email.header.make_header(email.header.decode_header(message["Subject"])))
    corps = message.get_payload()[0].get_payload(decode=True).decode()
    assert "1 Alerte(s)" in sujet and message["To"] == "moi@exemple.test"
    assert "Air &lt;Liquide&gt; (EUR)" in corps and "<Liquide>" not in corps
    assert "https://boursy.example" in corps and "72/100" in corps


def test_envoi_smtp(monkeypatch):
    envois = []

    class FauxSMTP:
        def __init__(self, serveur, port, timeout=None):
            envois.append(("connexion", serveur, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, identifiant, mot_de_passe):
            envois.append(("login", identifiant, mot_de_passe))

        def sendmail(self, expediteur, destinataire, corps):
            envois.append(("envoi", expediteur, destinataire))

    monkeypatch.setattr(smtplib, "SMTP_SSL", FauxSMTP)
    message = M.composer_email_alertes_radar("envoi@exemple.test", "moi@exemple.test", [])
    M.envoyer_smtp(message, "envoi@exemple.test", "secret", timeout=10)
    assert envois == [("connexion", "smtp.gmail.com", 465, 10), ("login", "envoi@exemple.test", "secret"),
                      ("envoi", "envoi@exemple.test", "moi@exemple.test")]
