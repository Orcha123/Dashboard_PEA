"""
Envoi des e-mails de Boursy (module sans Streamlit), partagé par l'application et par les tâches du soir.

Les identifiants SMTP (compte Gmail et mot de passe d'application) sont passés par l'appelant : l'application les lit
dans les secrets Streamlit, les tâches du soir dans les secrets GitHub.
"""
import html
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SERVEUR_SMTP, PORT_SMTP = "smtp.gmail.com", 465
ADRESSE_APPLICATION = "https://boursy.streamlit.app"


def envoyer_smtp(message, identifiant, mot_de_passe, timeout=20):
    """Envoie un message déjà composé (destinataire dans message["To"]). Lève une exception en cas d'échec."""
    with smtplib.SMTP_SSL(SERVEUR_SMTP, PORT_SMTP, timeout=timeout) as serveur:
        serveur.login(identifiant, mot_de_passe)
        serveur.sendmail(identifiant, message["To"], message.as_string())


def composer_email_alertes_radar(expediteur, destinataire, alertes, lien_application=ADRESSE_APPLICATION):
    """Rapport d'alertes envoyé à la demande depuis le Centre d'Alertes (valeurs sous cible ou en signal fort)."""
    message = MIMEMultipart("alternative")
    message["Subject"] = f"🔔 Boursy — {len(alertes)} Alerte(s) Prix Cible & Signaux"
    message["From"] = expediteur
    message["To"] = destinataire
    lignes = "".join(
        f"<li style='margin-bottom:8px;'><b>{html.escape(str(a['Actif']))}</b> : Cours <b>{html.escape(str(a['Prix']))}</b> "
        f"(Cible : {html.escape(str(a['Cible']))}) — Score : <b>{html.escape(str(a['Score']))}/100</b> ({html.escape(str(a['Motif']))})</li>"
        for a in alertes
    )
    corps = f"""
    <html><body style="font-family: Arial, sans-serif; color: #2c3e50;">
        <h2>📈 Rapport d'Alertes Boursy ({datetime.now().strftime('%d/%m/%Y')})</h2>
        <p>Votre radar a relevé les signaux suivants (information statistique, pas un conseil en investissement) :</p>
        <ul>{lignes}</ul>
        <p><a href="{html.escape(lien_application)}" style="background:#2ecc71; color:white; padding:10px 16px; text-decoration:none; border-radius:6px; font-weight:bold;">Ouvrir mon Dashboard Boursy</a></p>
    </body></html>
    """
    message.attach(MIMEText(corps, "html", "utf-8"))
    return message
