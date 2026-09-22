"""Die Felder, die ein Mitglied einzeln verbergen kann.

Herausgezogen aus ``models.py``: Formular, Mitgliederliste, Karte und Karten-Export
lesen dieselben Listen, das Modell braucht sie nur für ``field_visible_to()`` und die
Adress-Nullung im Signal.
"""

# Contact and address fields a member may individually hide from other members.
# When ANY of ADDRESS_TRIGGER_FIELDS is hidden, breite/laenge are nulled at save
# time so the address cannot be reconstructed from the coordinates.
PRIVACY_FIELDS = [
    "email", "xmpp",
    "telefon", "telefon_job", "telefon_mobil", "telefon_job_mobil", "fax",
    "geburtstag", "strasse", "plz", "ort",
]
ADDRESS_TRIGGER_FIELDS = {"strasse", "plz", "ort"}
