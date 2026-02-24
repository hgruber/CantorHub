import re
import unicodedata

from rapidfuzz import fuzz


def normalize(title):
    """
    Normalisiert einen Titel für die Vergleichbarkeit.

    Args:
        title (str): Der zu normalisierende Titel

    Returns:
        str: Der normalisierte Titel
    """
    title = title.lower()

    # Akzente entfernen
    title = unicodedata.normalize("NFKD", title)
    title = "".join(c for c in title if not unicodedata.combining(c))

    # feat., live, remaster usw. entfernen
    title = re.sub(r"\(.*?\)", "", title)
    title = re.sub(r"live.*", "", title)

    # Sonderzeichen raus
    title = re.sub(r"[^a-z0-9\s]", "", title)

    return " ".join(title.split())


def song_similarity(a, b):
    """
    Berechnet die Ähnlichkeit zwischen zwei Titeln unter Verwendung mehrerer Methoden
    und gibt das Maximum zurück.

    Args:
        a (str): Erster Titel
        b (str): Zweiter Titel

    Returns:
        int: Der Höchste Ähnlichkeitswert aus mehreren Methoden
    """
    a = normalize(a)
    b = normalize(b)
    return (
        0.40 * fuzz.token_set_ratio(a, b)
        + 0.25 * fuzz.token_sort_ratio(a, b)
        + 0.20 * fuzz.ratio(a, b)
        + 0.15 * fuzz.partial_ratio(a, b)
    )


def find_similar_titles(search_string, songs, limit=5):
    """
    Findet ähnliche Liedertitel unter Verwendung mehrerer Ähnlichkeitsmethoden.

    Args:
        search_string (str): Der Suchbegriff
        songs (list): Liste von Lied-Objekten
        limit (int): Anzahl der Ergebnisse (Standard: 5)

    Returns:
        list: Liste von Tupeln (Lied, Ähnlichkeitsbewertung) sortiert nach Bewertung
    """
    try:
        # Get all song titles
        titles = [(song, song.titel) for song in songs]

        # Find the best matches using the combined similarity function
        matches = []
        for song, title in titles:
            similarity = song_similarity(search_string, title)
            matches.append((song, similarity))

        # Sort by similarity score (descending) and limit results
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]

    except ImportError:
        # If rapidfuzz is not available, return empty list
        return []


def get_similar_titles(search_string, songs, limit=5):
    """
    Get similar song titles in a user-friendly format.

    Args:
        search_string (str): The string to search for
        songs (list): List of song objects
        limit (int): Number of results to return (default: 5)

    Returns:
        list: List of dictionaries with song information and similarity score
    """
    matches = find_similar_titles(search_string, songs, limit)
    return [
        {"song": song, "title": song.titel, "similarity": score}
        for song, score in matches
    ]
