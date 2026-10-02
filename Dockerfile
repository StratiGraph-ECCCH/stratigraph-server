# em-server — the s3Dgraphy access API over HTTP.
#
# Stateless by construction: no volume, no writable path the app depends on, no
# state in the container. Scale it by adding replicas.
#
#   docker build -t em-server .
#   docker run --rm -p 8000:8000 em-server
#
# The s3dgraphy version has a default, and it is a COPY — see the note below.
#
# To run against a s3Dgraphy CHECKOUT instead of the published wheel while the
# language and the service move together, do NOT try to build without one: this
# line used to say `--build-arg S3DGRAPHY_SPEC=""`, and pip refuses an empty
# requirement ("Expected package name at the start of dependency specifier") —
# measured, so the escape hatch never worked. The mechanism that does is the
# dev-stack overlay, which mounts the checkout and puts it first on PYTHONPATH:
#   ./dev-stack/fcn-up.sh --local-s3d
#
FROM python:3.12-slim AS base

# PYTHONDONTWRITEBYTECODE: nothing in the image should be modified at runtime.
# PYTHONUNBUFFERED: logs reach the orchestrator as they happen, not on flush.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# EXACT pin with the extras — see pyproject.toml for the three reasons. dev12 is
# the first release carrying `s3dgraphy/api.py`, and the extras are what make
# /v1/reproject and /v1/export-ttl work rather than 501.
#
# Build with --build-arg S3DGRAPHY_EXTRAS='' for a slimmer, less capable image:
# it starts and serves, and /v1/health reports which ops it cannot do.
# The s3Dgraphy this image installs: the VERSION from one place, the EXTRAS
# from this service.
#
# `S3DGRAPHY_VERSION` HAS A DEFAULT since 2026-10-24, and it is a copy.
#
# Until then it had none, on the argument that a default would be a second
# spelling of a number that must agree with the stack. The argument was right
# and the remedy did not hold: the "one place" it pointed at was
# `dev-stack/.env.dev`, which is gitignored and never carried the variable, so
# the real value lived in the compose anchor (dev17) while `pyproject.toml` —
# what the test suite installs — said dev12. Three spellings, three versions,
# measured by MICRO-CATENA-DATAMODEL on 30 September.
#
# So the version is now written BY HAND in one place, `pyproject.toml`, and
# copied to two: this default and the compose anchor `x-s3dgraphy-version`.
# `bump-s3dgraphy.sh` writes all three in one go, and
# `tests/test_s3dgraphy_pin.py` fails the suite the day any of them disagrees.
# A copy under a test is not a second source; an unguarded one would be.
#
#   docker build -t em-server .                                   # the pin
#   docker build --build-arg S3DGRAPHY_VERSION=<v> -t em-server . # an experiment
#
# The EXTRAS stay here because they are legitimately this service's own: `[geo]`
# and `[rdf]` are what make /v1/reproject and /v1/export-ttl work rather than
# answer 501. A service may choose what it needs; it may not move the version by
# itself.
ARG S3DGRAPHY_VERSION=1.6.0.dev31
ARG S3DGRAPHY_EXTRAS="geo,rdf"

WORKDIR /srv/em-server

# Dependencies first, in their own layer: application edits then rebuild in
# seconds instead of re-resolving the world.
COPY pyproject.toml README.md ./
# The explicit rdflib/pyproj lines are GONE, and the extras above are why: before
# dev12 there was no `[geo]`, so `s3dgraphy[rdf,geo]` silently skipped pyproj (pip
# WARNS about an unknown extra, it does not fail) and the image answered
# `reproject: false`. From dev12 on both extras are declared, so naming them is
# enough — verified in the container, not assumed.
# PyJWT[crypto] is here and NOT behind a build arg on purpose: an image that
# cannot verify a token is an image that would come up in the open dev mode on
# the shared infrastructure. The auth dependency is not optional (P1).
# `minio` is here and not behind a build arg for the same reason PyJWT is: an
# image that cannot reach the object store would come up serving assets from a
# container filesystem that disappears with the container. 400 KB.
# `psycopg[binary,pool]` is here for the THIRD time the same reason: da quando i
# documenti hanno una casa (`app/documents.py`) un'immagine senza il driver non
# potrebbe aprirla, e `EM_DOCUMENTS_*` configurato senza il client fallirebbe
# all'avvio — che è il modo giusto di fallire, ma solo se l'alternativa esiste.
# `[binary]` perché il wheel porta libpq dentro: niente `libpq-dev` da
# installare e niente compilatore in un'immagine che non ne ha uno.
RUN set -eu; \
    : "${S3DGRAPHY_VERSION:?an empty --build-arg; the pin is in pyproject.toml}"; \
    spec="s3dgraphy${S3DGRAPHY_EXTRAS:+[${S3DGRAPHY_EXTRAS}]}==${S3DGRAPHY_VERSION}"; \
    pip install --upgrade pip && \
    pip install "$spec" "fastapi>=0.110" "uvicorn[standard]>=0.27" \
                "PyJWT[crypto]>=2.8" "minio>=7.2" "psycopg[binary,pool]>=3.1"

COPY app ./app

# The licence text travels WITH the software, and not only in the repository.
# Publishing an image IS distributing, which is the act the GPL's obligations
# attach to, so the text has to be inside the thing that gets distributed.
# `/licenses` rather than a path of our own: it is where OpenShift and the Red
# Hat container guidelines look, so a machine can find it too.
COPY LICENSE /licenses/LICENSE

# ── L'IMMAGINE DICE COSA CONTIENE ───────────────────────────────────────────
#
# Un'immagine che non sa dire cosa contiene è irriproducibile nel modo
# peggiore, perché SEMBRA riproducibile: due build dello stesso tag portano lo
# stesso nome e cose diverse dentro.
#
# Qui sopra le dipendenze sono chieste con dei RANGE — `fastapi>=0.110`,
# `uvicorn[standard]>=0.27`, e le altre — e un range risolve a ciò che esisteva
# il giorno del build. (s3dgraphy no: la riga la costruisce con `==`, quindi è
# esatta per costruzione. È la ragione per cui i `>=` di `pyproject.toml` NON
# toccano questa immagine: il progetto non viene installato, solo le
# dipendenze nominate qui.)
#
# Quindi l'elenco di ciò che è finito dentro viene scritto DENTRO, da pip, nel
# momento in cui pip lo decide. Non è una lista che qualcuno mantiene: è il
# verbale di quel build.
#
#   /licenses/installed.txt       tutto, con le versioni risolte
#   /licenses/s3dgraphy-version   la sola riga che serve a un occhio
#
# In `/licenses` perché è il posto che questa immagine ha già per le cose che
# viaggiano con il software e si leggono da fuori.
RUN set -eu; \
    pip freeze --all > /licenses/installed.txt; \
    pip show s3dgraphy | sed -n 's/^Version: //p' > /licenses/s3dgraphy-version; \
    test -s /licenses/s3dgraphy-version

# E l'ETICHETTA, che è ciò che chi specchia l'immagine legge senza tirarla:
# `imagetools inspect` la dà da un registry pubblico senza credenziali.
#
# Il valore è l'ARGOMENTO — cioè quello che abbiamo CHIESTO — mentre il file
# qui sopra è quello che pip ha DATO. Tenerli separati è il punto: se un giorno
# `S3DGRAPHY_VERSION` diventasse un range, i due smetterebbero di coincidere, e
# `scripts/verifica-tirata-anonima.sh` li confronta a ogni pubblicazione. Una
# sola delle due fonti non avrebbe niente contro cui essere sbagliata.
LABEL org.stratigraph.s3dgraphy.version="${S3DGRAPHY_VERSION}"


# ── NOT ROOT, AND NOT A NAMED USER EITHER ────────────────────────────────────
#
# `USER emserver` was not wrong, it was not ENOUGH, and the gap is a whole class of
# deployment: OpenShift — which is what PSNC runs — IGNORES the name. It assigns
# the pod a RANDOM uid out of the project's range and puts it in group 0 as a
# supplementary group. So the process that starts is a user that owns NOTHING,
# and `/srv/em-data` (which it must write) was `emserver:emserver` mode 755.
# The container then either dies at boot or comes up unable to save, which is
# worse because it looks fine.
#
# Two changes, and they are the pattern Red Hat documents for arbitrary-uid
# images:
#
#   · the writable paths belong to GROUP 0 and the group bits equal the user
#     bits (`chown -R <uid>:0` + `chmod -R g=u`). Any uid the orchestrator
#     invents lands in group 0, so it can write them. Note that this is NOT
#     "world-writable": it is one group, the one the platform guarantees.
#   · `USER` is a NUMBER. Kubernetes evaluates `runAsNonRoot` against the UID,
#     and a name is not a uid: the kubelet cannot resolve it from outside the
#     image, so depending on the runtime it either refuses the pod or lets it
#     through unchecked. A number is verifiable.
#
# And `HOME`, which is the one that is invisible until it bites: Docker derives
# `HOME` from `/etc/passwd`, and a uid that is not in there gets `HOME=/`, which
# is not writable. Anything that wants a dot-directory then fails with an error
# about a path nobody configured. So HOME is named here and made group-writable
# like the rest.
#
# The proof is a RUN, not a reading: `docker run --user 12345:0` with a uid that
# does not exist in this image's `/etc/passwd` — see `dev-stack/uid-arbitrario.sh`.
#
# The paragraph this block replaces still holds, and is kept because it explains
# why the empty directory is created at all:
# Not root. The application writes nothing inside the image, so there is no
# reason to be able to.
#
# /srv/em-data is created here even though it is empty: a named volume mounted
# on a path the image does NOT have is created root-owned, and a non-root
# process then cannot write its first snapshot. Creating it with the right owner
# is what makes `volumes: [em_data:/srv/em-data]` work — in the dev stack and in
# the Ansible compose, which mounts exactly the same path.
ARG APP_UID=10001
RUN useradd --uid ${APP_UID} --gid 0 --create-home --shell /usr/sbin/nologin emserver && \
    mkdir -p /srv/em-data && \
    chown -R ${APP_UID}:0 /srv/em-server /srv/em-data /home/emserver && \
    chmod -R g=u /srv/em-server /srv/em-data /home/emserver
ENV HOME=/home/emserver
USER ${APP_UID}

EXPOSE 8000

# The orchestrator's own probe target — the same endpoint a human curls.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# One worker per container: replicas are the orchestrator's business, and a
# process count baked into an image is a decision taken in the wrong place.
#
# ── IL KEEPALIVE DEL TRASPORTO, SCRITTO INVECE CHE EREDITATO ─────────────────
#
# Questi due numeri erano già in vigore e non li aveva scelti nessuno: sono i
# default di uvicorn. Misurati il 30 settembre 2026 contro questa immagine
# (uvicorn 0.52.1, websockets 17.0.1), con un client vero e non il TestClient:
#
#   PING a t=20,0 · 40,0 · 60,0 s — periodo 20,0 s esatti
#   client che non risponde        → CLOSE a t=40,0 s, «keepalive ping timeout»
#   client in GALLERIA (pacchetti scartati, socket aperti da tutti e due i capi)
#                                  → il server chiude il suo capo a t=40,0 s,
#                                     e `/who` smette di dirlo seduto a t=40,2 s
#
# Quaranta secondi è un numero ragionevole e NON è la ragione per scriverlo. La
# ragione è che finché stava nei default di una dipendenza, un aggiornamento di
# uvicorn o un `--ws-ping-interval 0` in un playbook lo cambiava **in silenzio**
# — e la soglia del silenzio dell'applicazione (30 s, `app/presence.py`) è
# scelta per stare DENTRO questo numero. Se questo si allunga senza che nessuno
# se ne accorga, «uscito» arriva dopo «silenzioso» invece che dopo, e i tre
# stati tornano a essere due.
#
# `tests/test_chi_ce_e_chi_non_ce_piu.py` legge questa riga e confronta i numeri
# con quelli di `presence.py`: il vincolo è verificato, non commentato.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ws-ping-interval", "20", "--ws-ping-timeout", "20"]
