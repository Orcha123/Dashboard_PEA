"""
Habillage de Boursy : feuille de style, nombres au format français et affichage du HTML dans Streamlit.

- La feuille de style est dans habillage.css (CSS pur, modifiable sans toucher au code) ; appliquer_habillage()
  l'injecte au début de chaque page.
- nombres_fr() met les nombres au format français (11,709.45 -> 11 709,45) sans toucher aux balises HTML, à leurs
  attributs ni aux blocs <style>/<script> ; elle est couverte par tests/test_habillage.py.
"""
import os
import re

import streamlit as st

CHEMIN_FEUILLE_DE_STYLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "habillage.css")
_MOTIF_NOMBRE_FR = re.compile(r"(?<![\w.,/])(?<!IA )(?<!Boursy )(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)(?!\w|[.,/]\d)")


def nombres_fr(texte):
    """
    Met les nombres d'un texte au format français : 11,709.45 -> 11 709,45 (espace insécable et virgule décimale).
    Seul le texte affiché est touché : les balises HTML, leurs attributs et les blocs <style>/<script> restent intacts.
    """
    if not isinstance(texte, str) or not texte:
        return texte
    morceaux = re.split(r"(<[^>]+>)", texte)
    hors_texte = False
    for i_m, morceau in enumerate(morceaux):
        if morceau.startswith("<"):
            debut_balise = morceau[1:8].lower()
            if debut_balise.startswith(("style", "script")):
                hors_texte = True
            elif debut_balise.startswith(("/style", "/script")):
                hors_texte = False
        elif not hors_texte:
            morceaux[i_m] = _MOTIF_NOMBRE_FR.sub(lambda m: m.group(1).replace(",", " ").replace(".", ","), morceau)
    return "".join(morceaux)


def preparer_html(html_brut):
    """
    HTML prêt pour st.markdown : indentations retirées (sinon Streamlit l'affiche en bloc de code), chaque tableau
    placé dans un cadre défilant (lisible sur mobile sans élargir la page), nombres au format français.
    """
    html_propre = "\n".join(ligne.strip() for ligne in html_brut.splitlines() if ligne.strip())
    html_propre = re.sub(r"<table\s+class=(['\"])r-table\1", r'<div class="r-wrap"><table class="r-table"', html_propre)
    html_propre = html_propre.replace("</table>", "</table></div>")
    return nombres_fr(html_propre)


def afficher_html(html_brut):
    st.markdown(preparer_html(html_brut), unsafe_allow_html=True)


def markdown_fr(texte, **options):
    """st.markdown avec les nombres au format français."""
    st.markdown(nombres_fr(texte), **options)


def feuille_de_style():
    """Contenu de habillage.css, entre balises <style>."""
    with open(CHEMIN_FEUILLE_DE_STYLE, encoding="utf-8") as fichier:
        return "\n<style>\n" + fichier.read() + "</style>\n"


def appliquer_habillage():
    afficher_html(feuille_de_style())
