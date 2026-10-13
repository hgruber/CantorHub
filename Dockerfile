# Stage 1: Base build stage
FROM python:3.14-slim AS builder

# Install build dependencies for mysqlclient
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Create the app directory
RUN mkdir /app

# Set the working directory
WORKDIR /app

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Upgrade pip and install dependencies
RUN pip install --upgrade pip

# Copy the requirements file first (better caching)
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Production stage
FROM python:3.14-slim

RUN useradd -m -r appuser && \
    mkdir /app && \
    chown -R appuser /app

# Copy the Python dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.14/site-packages/ /usr/local/lib/python3.14/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
# tzdata steht hier ausdruecklich, obwohl die Basis es derzeit mitbringt: bei
# USE_TZ = False ist jede Zeit im Portal naive Ortszeit, und Django setzt aus
# TIME_ZONE die Variable TZ samt time.tzset(). Ohne /usr/share/zoneinfo fiele
# das still auf UTC zurueck — jede Uhrzeit waere um ein bis zwei Stunden
# verschoben, ohne Fehlermeldung. Zu wichtig, um es einem Basisabbild zu
# ueberlassen; das Python-Paket tzdata aus requirements.txt bedient nur
# zoneinfo, nicht tzset.
#
# Die Locale dagegen fehlt in python:3.14-slim wirklich, und das alte
# "locale-gen de_DE.UTF-8" half nicht: locale-gen liest in Debian ausschliesslich
# /etc/locale.gen und ignoriert sein Argument (anders als in Ubuntu). Folge war,
# dass intern/replacements.py:format_datetime auf englische Monatsnamen zurueck-
# fiel. Deshalb erst die Zeile schreiben, dann generieren. MonatsnamenTest in
# intern/tests.py haelt das fest.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx locales tzdata libmariadb3 && \
    echo 'de_DE.UTF-8 UTF-8' > /etc/locale.gen && \
    locale-gen && \
    echo 'LANG=de_DE.UTF-8' > /etc/default/locale && \
    echo 'LC_ALL=de_DE.UTF-8' >> /etc/default/locale && \
    rm -f /etc/nginx/sites-enabled/default && \
    rm -rf /var/lib/apt/lists/* \
           /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
           /usr/local/lib/python3.14/site-packages/pip \
           /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.14/site-packages/setuptools \
           /usr/local/lib/python3.14/site-packages/setuptools-*.dist-info \
           /usr/local/lib/python3.14/site-packages/wheel \
           /usr/local/lib/python3.14/site-packages/wheel-*.dist-info \
           /usr/local/lib/python3.14/site-packages/pkg_resources \
           /usr/local/lib/python3.14/site-packages/_distutils_hack \
           /usr/local/lib/python3.14/site-packages/distutils-precedence.pth \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14 \
           /usr/local/bin/wheel

# Deutsch und Berlin sind die Vorgaben — es ist ein deutsches Projekt. Sprache
# und Zeitzone sind zur Laufzeit ueber die Konfigurationsschluessel SPRACHE und
# ZEITZONE aenderbar; TZ hier sorgt dafuer, dass auch nginx-Logs und
# Shell-Werkzeuge im Container die Portalzeit zeigen.
ENV LANG=de_DE.UTF-8
ENV LC_ALL=de_DE.UTF-8
ENV TZ=Europe/Berlin

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Alles Veraenderliche liegt hier, nichts davon im Abbild: Uploads, Kachelcache,
# der Schluessel, eine etwaige SQLite-Datei. Beim Betrieb ein Volume.
ENV CANTORHUB_DATA=/data
RUN mkdir -p /data && chown -R appuser /data

# Die nackte Versionsnummer, von build.sh aus "git describe --tags" gefuellt
# (v1.0.0 bzw. v1.0.0-7-g7c8b717). Das Abbild traegt kein git; ohne dieses
# Argument zeigt die Seitenleiste nur „CantorHub".
ARG CANTORHUB_VERSION=""
ENV CANTORHUB_VERSION=${CANTORHUB_VERSION}

COPY nginx.conf /etc/nginx/
WORKDIR /app

# Application code. Was draussen bleibt, steht in .containerignore.
COPY --chown=appuser:appuser . .

# Statische Dateien sind ein Bauergebnis, kein Betriebsdatum: einmal hier statt
# bei jedem Containerstart. DEBUG=1 nur fuer diesen Aufruf, damit kein
# Schluessel noetig ist — er wuerde sonst im Abbild landen. Bricht
# ManifestStaticFilesStorage an einer fehlenden .map-Datei ab, scheitert damit
# der Bau statt spaeter der Start.
RUN DEBUG=1 python manage.py collectstatic --noinput

# Expose the application port
EXPOSE 8000

# Noch als root: nginx braucht fuer einen unprivilegierten Lauf beschreibbare
# pid- und temp-Pfade, und ein frisch angelegtes Volume gehoert root.
#USER appuser

# Start the application using Gunicorn
CMD ["/app/start.sh"]
