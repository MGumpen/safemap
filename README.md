# SafeMap

![CI Status](https://github.com/MGumpen/safemap/actions/workflows/ci.yml/badge.svg)

SafeMap er et GIS-basert prosjekt som undersøker totalforsvaret i Norge gjennom geografisk analyse av samfunnets beredskap og robusthet. Prosjektet bruker åpne geodata til å identifisere sårbarheter, avhengigheter og tilgjengelighet knyttet til innbyggere og kritisk infrastruktur, med mål om å støtte både offentlige beslutninger og økt beredskapsforståelse hos befolkningen.

Appen er en prosjektoppgave i faget IS-218 Geografiske informasjonssystemer, IT og IoT ved UiA i samarbeid med Kartverket og Norkart.

Prosjektoppgaven har fokus på totalforsvarsåret 2026.

## 🚀 CI/CD

Dette prosjektet bruker GitHub Actions for automatisk bygging og testing av koden.

### Automatiske bygge-prosesser

Når kode pushes til `main` eller `develop` branch, kjører følgende automatisk:

- ✅ **Testing** på Python 3.10, 3.11 og 3.12
- 🔍 **Kodekvalitet** - linting med Ruff og typesjekking med mypy
- 🔒 **Sikkerhetsskanning** - automatisk sjekk for sårbarheter med Bandit
- 📦 **Bygging** av applikasjonen
- 📊 **Testdekning** - generering av coverage-rapporter

### Branch Protection

For å sikre kodekvalitet er `main` branch beskyttet med obligatoriske status-sjekker:
- Alle CI-tester må bestå før merge
- Pull requests er påkrevd
- Code review er påkrevd

**Se [.github/BRANCH_PROTECTION.md](.github/BRANCH_PROTECTION.md) for instruksjoner om hvordan du aktiverer branch protection.**

### Deployment

Ved publisering av en ny release, bygges applikasjonen automatisk og klargjøres for deployment.

### Mer informasjon

Se [.github/workflows/README.md](.github/workflows/README.md) for detaljert dokumentasjon om CI/CD-oppsettet.