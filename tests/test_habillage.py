"""Tests de l'habillage : format français des nombres et préparation du HTML (python -m pytest tests)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import habillage as H  # noqa: E402

ESPACE = " "


def test_nombres_au_format_francais():
    assert H.nombres_fr("Valeur : 11,709.45 €") == f"Valeur : 11{ESPACE}709,45 €"
    assert H.nombres_fr("PRU 54.2 et 1,234,567") == f"PRU 54,2 et 1{ESPACE}234{ESPACE}567"
    assert H.nombres_fr("Coach IA 2.0 de Boursy 2.0") == "Coach IA 2.0 de Boursy 2.0"  # noms de version intacts
    assert H.nombres_fr("le 12/05/2026 à 9.5") == "le 12/05/2026 à 9,5"  # les dates ne bougent pas
    assert H.nombres_fr("v1.2.3") == "v1.2.3"
    assert H.nombres_fr("") == "" and H.nombres_fr(None) is None and H.nombres_fr(12.5) == 12.5


def test_balises_styles_et_scripts_intacts():
    html = "<div style='width: 12.5%; opacity: 0.75'>Total 1,500.25</div><style>.a { width: 33.3%; }</style><script>x = 1.5;</script>"
    resultat = H.nombres_fr(html)
    assert "width: 12.5%; opacity: 0.75" in resultat and ".a { width: 33.3%; }" in resultat and "x = 1.5;" in resultat
    assert f"Total 1{ESPACE}500,25" in resultat


def test_preparation_du_html():
    resultat = H.preparer_html("""
        <table class='r-table'>
            <tr><td>3.5 %</td></tr>
        </table>
    """)
    assert resultat.startswith('<div class="r-wrap"><table class="r-table">') and resultat.endswith("</table></div>")
    assert "\n    " not in resultat and "3,5 %" in resultat  # indentation retirée, format français


def test_feuille_de_style():
    style = H.feuille_de_style()
    assert style.strip().startswith("<style>") and style.strip().endswith("</style>")
    assert ".argon-card" in style and ".r-table" in style and "@media" in style
    assert H.preparer_html(style).count("0.75") == style.count("0.75")  # la feuille de style n'est jamais reformatée
