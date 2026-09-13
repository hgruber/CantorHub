"""Passwort-Hasher des Portals.

Django 6 fährt PBKDF2 mit 1.200.000 Iterationen; eine Anmeldung kostet damit je
nach CPU eine halbe bis zwei Sekunden reine Rechenzeit, und da gunicorn hier mit
drei synchronen Arbeitsprozessen läuft, blockiert jede davon einen ganzen
Prozess. `ITERATIONEN` senkt das bewusst auf einen Wert unterhalb der
OWASP-Empfehlung (600.000): das Portal führt keine Zahlungs- oder
Gesundheitsdaten, und der Iterationswert schützt ausschließlich den Fall, dass
jemand die Datenbank erbeutet und Passwörter offline durchprobiert — er ist kein
Schutz gegen Anmeldeversuche über das Portal. Die gewählten 200.000 liegen noch
über dem, was der abgelöste PHP-Hash mitbrachte (100.000, siehe
`php_pbkdf2_hasher.py`), und in derselben Größenordnung wie Djangos eigener
Standardwert bis Version 3.2.

Wichtig: Djangos eingebauter `PBKDF2PasswordHasher` darf nicht zusätzlich in
`PASSWORD_HASHERS` stehen. `get_hashers_by_algorithm()` baut ein Dictionary über
`hasher.algorithm`, bei gleichem Algorithmus gewinnt also der *letzte* Eintrag
der Liste — und dessen `must_update()` würde jeden hier geschriebenen Hash sofort
wieder auf 1.200.000 Iterationen hochrechnen.
"""

from django.contrib.auth.hashers import PBKDF2PasswordHasher


class PortalPBKDF2Hasher(PBKDF2PasswordHasher):
    """PBKDF2-SHA256 mit reduziertem Iterationswert.

    `algorithm` bleibt unverändert `pbkdf2_sha256`: bestehende Hashes werden
    weiterhin erkannt und mit ihrem jeweils gespeicherten Iterationswert geprüft.
    Beim ersten Login nach der Umstellung greift `must_update()` und schreibt den
    Hash mit dem neuen Wert zurück — dieser eine Login kostet also noch einmal
    den alten Preis.
    """

    iterations = 200_000
