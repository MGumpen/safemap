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

- Python 3.10 eller nyere
- Git

### Installasjon

```bash
# Klon repositoriet
git clone https://github.com/MGumpen/safemap.git
cd safemap

# Opprett virtuelt miljø
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Installer avhengigheter
pip install -r requirements.txt
```

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

## Docker

Kjør appen likt hos alle med Docker:

1. Kopiér [\.env.example](.env.example) til `.env` og fyll inn riktige databaseverdier.
2. Start:

```bash
docker compose up --build
```

Appen blir tilgjengelig på `http://localhost:8000`.

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