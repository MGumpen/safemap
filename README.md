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

## Bidra

Vi setter pris på bidrag til prosjektet. Les [CONTRIBUTING.md](CONTRIBUTING.md) for retningslinjer om hvordan du bidrar, inkludert:

- Oppsett av utviklingsmiljø
- Coding standards
- Testing-krav
- Pull request prosess

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

## Video av system
https://github.com/MGumpen/safemap/issues/26#issue-3983429669
