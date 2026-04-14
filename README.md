# SafeMap

SafeMap er et GIS-basert prosjekt som undersøker totalforsvaret i Norge gjennom geografisk analyse av samfunnets beredskap og robusthet. Prosjektet bruker åpne geodata til å identifisere sårbarheter, avhengigheter og tilgjengelighet knyttet til innbyggere og kritisk infrastruktur, med mål om å støtte både offentlige beslutninger og økt beredskapsforståelse hos befolkningen.

Prosjektet er en del av faget IS-218 Geografiske informasjonssystemer, IT og IoT ved Universitetet i Agder, utviklet i samarbeid med Kartverket og Norkart. Fokusområdet er totalforsvarsåret 2026.

## Teknisk Stack

- **Backend**: Python 3.10+
- **Frontend**: HTML, CSS
- **GIS**: Åpne geodata fra norske kilder
- **CI/CD**: GitHub Actions

## Kom i gang

### Forutsetninger

- Docker Desktop (eller Docker Engine + Docker Compose)
- Git

### Start prosjektet

```bash
# Klon repositoriet
git clone https://github.com/MGumpen/safemap.git
cd safemap

# Lag .env-fil i prosjektroten med disse variablene:
# user=
# password=
# host=
# port=
# dbname=

# Bygg og start appen
docker compose up --build
```

Appen blir tilgjengelig på `http://localhost:8000`.

`docker compose down` stopper appen.

## Utvikling

### Prosjektstruktur

```
safemap/
├── .github/          # CI/CD workflows og konfigurasjon
├── src/              # Applikasjonskode
├── tests/            # Tester
├── static/           # HTML, CSS, JavaScript
└── requirements.txt  # Python-avhengigheter
```

### Importer JSON-kilder til databasen

Kartet kan fortsatt lese punktdata direkte fra JSON-filene i `src/`, men de samme
filene kan speiles inn i PostGIS for spatial SQL-analyse.

```bash
python3 scripts/import_geojson_to_postgis.py --dataset all
```

Eller i prosjektets Docker-miljo:

```bash
docker compose exec safemap python /scripts/import_geojson_to_postgis.py --dataset all
```

Dette oppretter og fyller disse tabellene:

- `sykehus_points`
- `legevakt_points`

For aa kun validere JSON-formatet uten databaseendringer:

```bash
python3 scripts/import_geojson_to_postgis.py --dataset all --dry-run
```

Denne losningen lar dere beholde JSON som del av Oppgave 1, samtidig som de samme
punktene finnes i databasen for dynamiske PostGIS-sporringer i neste del av kartet.



### Arkitekturskisse

<img width="1163" height="519" alt="image" src="https://github.com/user-attachments/assets/04643f51-03c3-41f5-8011-3cb18b021f90" />


### Kodekvalitet

Prosjektet bruker følgende verktøy for å sikre høy kodekvalitet:

- **Ruff**: Linting og formattering
- **mypy**: Type checking
- **Bandit**: Sikkerhetsskanning
- **pytest**: Testing og coverage

Kjør kvalitetssjekker lokalt før commit:

```bash
ruff check .
ruff format .
mypy .
pytest
```

## Continuous Integration

GitHub Actions kjører automatisk ved push til `main` eller `dev` branch:

- Testing på Python 3.10, 3.11 og 3.12
- Kodekvalitetssjekk med Ruff og mypy
- Sikkerhetsskanning med Bandit
- Generering av testdekning
- Bygging av applikasjonen

### Branch Protection

`main` branch er beskyttet med obligatoriske status-sjekker:
- Alle CI-tester må bestå før merge
- Pull requests kreves
- Code review kreves

Se [.github/BRANCH_PROTECTION.md](.github/BRANCH_PROTECTION.md) for konfigurasjonsinstruksjoner.


## Lisens

Dette prosjektet er lisensiert under vilkårene i [LICENSE](LICENSE)-filen.

## Kontakt

Prosjektet er utviklet som en del av IS-218 ved Universitetet i Agder i samarbeid med Kartverket og Norkart.

## Dokumentasjon

- [CI/CD Workflows](.github/workflows/README.md) - Detaljert dokumentasjon om automatisering
- [Branch Protection](.github/BRANCH_PROTECTION.md) - Instruksjoner for branch protection
- [Contributing](CONTRIBUTING.md) - Guide for bidragsytere

## Refleksjon

- Vi kan forbedre struktureringen av prosjektet slik at koden blir lettere å vedlikeholde.
- Dokumentasjonen bør være mer detaljert, spesielt rundt valg av teknologier og arkitektur.
- Testdekningen er for lav og bør økes for å sikre stabilitet.
- Vi kunne hatt bedre tidsplanlegging for å unngå siste‑liten endringer.
- Brukeropplevelsen kan finjusteres med mer tilbakemelding fra reelle brukere.

## Oppgave 2

### Beskrivelse av utvidelsen

I Oppgave 2 har vi utvidet webkartet med romlig analyse basert paa PostGIS og databaseoppslag ved brukerinteraksjon.

Det viktigste som er lagt til er:

- Brukeren kan klikke i kartet eller velge en adresse og få en dynamisk analyse av punktet.
- Frontend sender koordinatene til backend, som kaller en SQL-funksjon i
  databasen.
- SQL-funksjonen finner naermeste sykehus, legevakt, brannstasjon og
  tilfluktsrom ved hjelp av PostGIS.
- Hver kategori gir en delscore basert på avstand, og alle delpoengene summeres til en total beredskapsscore på 100.
- Kartet gir visuell feedback ved å vise klikkpunkt, fremheving av nærmeste ressurser og et eget sonelag for beredskapsscore i kartutsnittet.

### SQL-snippet

Under er SQL-funksjonen som brukes for punktanalysen. Den kan lagres i Supabase
og viser hvordan vi bruker PostGIS-funksjoner som `ST_DWithin`,
`ST_Distance`, `ST_Transform`, `ST_MakePoint` og `ST_GeomFromText`.

```sql
CREATE OR REPLACE FUNCTION public.analyze_location_score(
    input_lat DOUBLE PRECISION,
    input_lon DOUBLE PRECISION
)
RETURNS JSONB
LANGUAGE sql
AS $$
WITH origin AS (
    SELECT
        ST_SetSRID(ST_MakePoint(input_lon, input_lat), 4326) AS geom_4326,
        ST_SetSRID(ST_MakePoint(input_lon, input_lat), 4326)::geography AS geog_4326
),
nearest_hospital AS (
    SELECT
        1 AS sort_order,
        'hospital'::text AS key,
        'Sykehus'::text AS label,
        h.navn AS name,
        COALESCE(h.adresse, h.poststed, h.kommune, 'Sykehus') AS description,
        ST_Y(h.geom) AS lat,
        ST_X(h.geom) AS lon,
        ST_Distance(h.geom::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(h.geom::geography, o.geog_4326, 80000) AS within_max_distance,
        20::integer AS max_score,
        20000::double precision AS ideal_distance_m,
        80000::double precision AS max_distance_m
    FROM sykehus_points h
    CROSS JOIN origin o
    ORDER BY ST_Distance(h.geom::geography, o.geog_4326)
    LIMIT 1
),
nearest_legevakt AS (
    SELECT
        2 AS sort_order,
        'legevakt'::text AS key,
        'Legevakt'::text AS label,
        l.navn AS name,
        COALESCE(l.adresse, l.poststed, l.kommune, 'Legevakt') AS description,
        ST_Y(l.geom) AS lat,
        ST_X(l.geom) AS lon,
        ST_Distance(l.geom::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(l.geom::geography, o.geog_4326, 30000) AS within_max_distance,
        25::integer AS max_score,
        8000::double precision AS ideal_distance_m,
        30000::double precision AS max_distance_m
    FROM legevakt_points l
    CROSS JOIN origin o
    ORDER BY ST_Distance(l.geom::geography, o.geog_4326)
    LIMIT 1
),
nearest_brannstasjon AS (
    SELECT
        3 AS sort_order,
        'fire_station'::text AS key,
        'Brannstasjon'::text AS label,
        COALESCE(b."brannstasjon", 'Brannstasjon') AS name,
        COALESCE(b."brannvesen", b."objtype", 'Brannstasjon') AS description,
        ST_Y(ST_Transform(b."SHAPE", 4326)) AS lat,
        ST_X(ST_Transform(b."SHAPE", 4326)) AS lon,
        ST_Distance(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326) AS distance_meters,
        ST_DWithin(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326, 10000) AS within_max_distance,
        25::integer AS max_score,
        2000::double precision AS ideal_distance_m,
        10000::double precision AS max_distance_m
    FROM "Brannstasjoner" b
    CROSS JOIN origin o
    ORDER BY ST_Distance(ST_Transform(b."SHAPE", 4326)::geography, o.geog_4326)
    LIMIT 1
),
nearest_shelter AS (
    SELECT
        4 AS sort_order,
        'shelter'::text AS key,
        'Tilfluktsrom'::text AS label,
        COALESCE(t.adresse, 'Tilfluktsrom') AS name,
        CASE
            WHEN t.plasser IS NOT NULL THEN CONCAT(t.plasser, ' plasser')
            ELSE 'Tilfluktsrom'
        END AS description,
        ST_Y(ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)) AS lat,
        ST_X(ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)) AS lon,
        ST_Distance(
            ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
            o.geog_4326
        ) AS distance_meters,
        ST_DWithin(
            ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
            o.geog_4326,
            5000
        ) AS within_max_distance,
        30::integer AS max_score,
        1000::double precision AS ideal_distance_m,
        5000::double precision AS max_distance_m
    FROM tilfluktsrom t
    CROSS JOIN origin o
    ORDER BY ST_Distance(
        ST_Transform(ST_GeomFromText(t.wkt_geom, 25833), 4326)::geography,
        o.geog_4326
    )
    LIMIT 1
),
nearest_targets AS (
    SELECT * FROM nearest_hospital
    UNION ALL
    SELECT * FROM nearest_legevakt
    UNION ALL
    SELECT * FROM nearest_brannstasjon
    UNION ALL
    SELECT * FROM nearest_shelter
),
scored AS (
    SELECT
        sort_order,
        key,
        label,
        name,
        description,
        lat,
        lon,
        ROUND(distance_meters)::integer AS distance_meters,
        ROUND((distance_meters / 1000.0)::numeric, 2) AS distance_km,
        within_max_distance,
        max_score,
        ideal_distance_m::integer AS ideal_distance_m,
        max_distance_m::integer AS max_distance_m,
        CASE
            WHEN distance_meters <= ideal_distance_m THEN max_score
            WHEN distance_meters >= max_distance_m THEN 0
            ELSE ROUND(
                max_score * (
                    (max_distance_m - distance_meters) / NULLIF(max_distance_m - ideal_distance_m, 0)
                )
            )::integer
        END AS score
    FROM nearest_targets
)
SELECT jsonb_build_object(
    'clicked_point',
    jsonb_build_object(
        'lat', input_lat,
        'lon', input_lon
    ),
    'score',
    COALESCE((SELECT SUM(score) FROM scored), 0),
    'max_score',
    100,
    'breakdown',
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'key', key,
                    'label', label,
                    'name', name,
                    'description', description,
                    'lat', lat,
                    'lon', lon,
                    'distance_meters', distance_meters,
                    'distance_km', distance_km,
                    'within_max_distance', within_max_distance,
                    'score', score,
                    'max_score', max_score,
                    'ideal_distance_m', ideal_distance_m,
                    'max_distance_m', max_distance_m,
                    'score_ratio', ROUND(score::numeric / NULLIF(max_score, 0), 4)
                )
                ORDER BY sort_order
            )
            FROM scored
        ),
        '[]'::jsonb
    )
);
$$;
```

## Video av system oppgave 1
https://github.com/MGumpen/safemap/issues/26#issue-3983429669

## Video av systemet oppgave 2
https://github.com/MGumpen/safemap/issues/31

## Notebook

Se notebooken her:  
[Åpne Jupyter Notebook](./Romlig_Analyse-1.ipynb)
