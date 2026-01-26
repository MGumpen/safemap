# SafeMap - Oppsettguide

Denne guiden viser hvordan du setter opp og kjører SafeMap-prosjektet.

## Forutsetninger

- **Python 3.10+**
- **Node.js 18+** og npm
- **PostgreSQL 14+** med PostGIS-utvidelse
- Git

---

## 1. Database-oppsett (PostgreSQL + PostGIS)

### Installer PostgreSQL og PostGIS

**Windows (med installasjonsveiviser):**
1. Last ned PostgreSQL fra https://www.postgresql.org/download/windows/
2. Velg å installere PostGIS som tillegg under installasjonen

**Eller med Docker:**
```bash
docker run -d \
  --name safemap-db \
  -e POSTGRES_USER=safemap \
  -e POSTGRES_PASSWORD=safemap \
  -e POSTGRES_DB=safemap \
  -p 5432:5432 \
  postgis/postgis:16-3.4
```

### Opprett database og kjør skjema

```bash
# Koble til PostgreSQL
psql -U postgres

# Opprett database og bruker
CREATE USER safemap_user WITH PASSWORD 'ditt_passord';
CREATE DATABASE safemap OWNER safemap_user;
\c safemap
CREATE EXTENSION postgis;
\q

# Kjør skjemaet
psql -U safemap_user -d safemap -f database/schema.sql
```

---

## 2. Backend-oppsett (Python/FastAPI)

### Opprett virtuelt miljø og installer avhengigheter

```bash
cd safemap

# Opprett virtuelt miljø
python -m venv venv

# Aktiver (Windows)
venv\Scripts\activate

# Aktiver (Mac/Linux)
source venv/bin/activate

# Installer avhengigheter
pip install -r requirements.txt
```

### Konfigurer miljøvariabler

```bash
# Kopier eksempelfil
copy .env.example .env

# Rediger .env og sett DATABASE_URL
# DATABASE_URL=postgresql://safemap_user:ditt_passord@localhost:5432/safemap
```

### Importer POI-data

```bash
# Kjør ingest-scriptet
python scripts/ingest_poi_data.py --db-url "postgresql://safemap_user:ditt_passord@localhost:5432/safemap"
```

Dette henter:
- **Brannstasjoner** fra DSB (offisiell norsk kilde)
- **Sykehus** fra OpenStreetMap
- **Politistasjoner** fra OpenStreetMap

### Start backend-serveren

```bash
uvicorn backend.main:app --reload --port 8000
```

API-dokumentasjon er tilgjengelig på: http://localhost:8000/docs

---

## 3. Frontend-oppsett (React/Vite)

### Installer npm-avhengigheter

```bash
cd frontend
npm install
```

### Start utviklingsserver

```bash
npm run dev
```

Frontend kjører på: http://localhost:5173

---

## 4. Verifiser at alt fungerer

1. Åpne http://localhost:5173 i nettleseren
2. Du skal se et kart over Norge med Kartverket-bakgrunn
3. Klikk på kartet for å se sikkerhetsscoren for det punktet
4. Sjekk at score-panelet viser avstand til brannstasjon, sykehus og politi

### API-helsesjekk

```bash
curl http://localhost:8000/health
```

Forventet respons:
```json
{"status":"ok","database":true,"version":"v1.0"}
```

### Test scoring-endpoint

```bash
curl "http://localhost:8000/score?lat=59.91&lng=10.75"
```

---

## Prosjektstruktur

```
safemap/
├── backend/                 # FastAPI-backend
│   ├── main.py             # API-endepunkter
│   ├── scoring.py          # Scoring-logikk
│   ├── database.py         # Database-tilkobling
│   ├── schemas.py          # Pydantic-modeller
│   └── config.py           # Konfigurasjon
├── frontend/               # React-frontend
│   ├── src/
│   │   ├── App.tsx         # Hovedkomponent
│   │   ├── components/     # UI-komponenter
│   │   ├── api.ts          # API-klienter
│   │   └── types.ts        # TypeScript-typer
│   └── package.json
├── database/
│   └── schema.sql          # PostGIS-skjema
├── config/
│   ├── scoring_config.yaml # Scoring-parametere
│   └── data_sources.yaml   # Datakilder
├── scripts/
│   ├── ingest_poi_data.py  # Data-import
│   └── verify_overpass_data.py
└── requirements.txt        # Python-avhengigheter
```

---

## Feilsøking

### "Database connection failed"
- Sjekk at PostgreSQL kjører: `pg_isready`
- Verifiser DATABASE_URL i .env

### "No POIs found"
- Kjør ingest-scriptet på nytt
- Sjekk `SELECT COUNT(*) FROM poi;` i databasen

### Frontend viser ikke kart
- Sjekk at Leaflet CSS er lastet (se index.html)
- Åpne utviklerverktøy (F12) og se etter feil i konsollen

---

## Neste steg

- [ ] Legg til grid-visning (heatmap) på kartet
- [ ] Implementer caching av beregnede scores
- [ ] Legg til flere POI-typer (legevakt, sivilforsvarsanlegg)
- [ ] Optimaliser for store datasett med vektortiles
