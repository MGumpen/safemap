# Bidra til SafeMap

Takk for interessen i å bidra til SafeMap! Denne guiden hjelper deg med å komme i gang.

## 🚀 Komme i gang

### Forutsetninger

- Python 3.10 eller nyere
- Git

### Oppsett av utviklingsmiljø

1. **Klon repositoriet**
   ```bash
   git clone https://github.com/MGumpen/safemap.git
   cd safemap
   ```

2. **Opprett virtuelt miljø**
   ```bash
   python -m venv venv
   source venv/bin/activate  # På Windows: venv\Scripts\activate
   ```

3. **Installer avhengigheter**
   ```bash
   pip install -r requirements.txt
   # For utviklingsverktøy:
   pip install ruff mypy pytest pytest-cov bandit
   ```

## 📝 Utviklingsprosess

### Workflow

1. **Opprett en ny branch**
   ```bash
   git checkout -b feature/min-nye-funksjon
   ```

2. **Gjør endringer**
   - Skriv kode
   - Legg til tester
   - Oppdater dokumentasjon

3. **Sjekk kodekvalitet lokalt**
   ```bash
   # Linting
   ruff check .
   
   # Formattering
   ruff format .
   
   # Typesjekking
   mypy .
   
   # Sikkerhetsskanning
   bandit -r .
   ```

4. **Kjør tester**
   ```bash
   pytest tests/ --cov=.
   ```

5. **Commit og push**
   ```bash
   git add .
   git commit -m "Beskrivende commit-melding"
   git push origin feature/min-nye-funksjon
   ```

6. **Opprett Pull Request**
   - Gå til GitHub
   - Opprett en Pull Request fra din branch til `develop`
   - Vent på at CI-tester kjører (automatisk)
   - Be om code review fra teamet

## ✅ CI/CD Pipeline

Når du pusher kode eller oppretter en Pull Request, kjører GitHub Actions automatisk:

### Continuous Integration (CI)

CI-pipelinen sjekker at koden din:
- Bygger uten feil
- Passerer alle tester
- Følger kodestandarder (linting)
- Ikke inneholder sikkerhetssårbarheter
- Har god typedekning

Du kan se statusen i Pull Request-en din. Alle sjekker må være grønne før koden kan merges.

### Continuous Deployment (CD)

CD-pipelinen aktiveres når:
- En ny release publiseres
- Manuelt trigger fra GitHub Actions

## 🧪 Testing

### Skrive tester

Plasser tester i `tests/` katalogen:

```python
# tests/test_example.py
def test_something():
    assert True
```

### Kjøre tester

```bash
# Alle tester
pytest

# Med coverage
pytest --cov=.

# Spesifikk test
pytest tests/test_example.py::test_something
```

## 📋 Kodestandarder

### Python Style Guide

- Følg PEP 8
- Bruk Ruff for linting og formatting
- Bruk type hints der det er hensiktsmessig
- Skriv docstrings for funksjoner og klasser

### Commit-meldinger

Bruk tydelige og beskrivende commit-meldinger:

```
✅ Gode eksempler:
- "Legg til funksjon for å hente geodata fra Kartverket"
- "Fiks bug i koordinattransformasjon"
- "Oppdater README med installasjonsinstruksjoner"

❌ Dårlige eksempler:
- "fix"
- "update"
- "asdf"
```

### Branch-navngivning

- `feature/beskrivelse` - for nye funksjoner
- `bugfix/beskrivelse` - for feilrettinger
- `hotfix/beskrivelse` - for kritiske feilrettinger
- `docs/beskrivelse` - for dokumentasjonsendringer

## 🔒 Sikkerhet

- Aldri commit hemmeligheter (API-nøkler, passord, etc.)
- Bruk `.env` filer for sensitive data (som er inkludert i `.gitignore`)
- Rapporter sikkerhetssårbarheter privat til teamet

## 📚 Ressurser

- [GitHub Actions Documentation](https://docs.github.com/actions)
- [Python Testing with pytest](https://docs.pytest.org/)
- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [GeoPandas Documentation](https://geopandas.org/) (når vi begynner med GIS-kode)

## 💬 Spørsmål?

Hvis du har spørsmål eller trenger hjelp:
- Opprett et issue i GitHub
- Kontakt teamet
- Se dokumentasjonen i `.github/workflows/README.md`

## 📄 Lisens

Ved å bidra til dette prosjektet, godtar du at dine bidrag blir lisensiert under samme lisens som prosjektet.

---

Takk for at du bidrar til SafeMap! 🗺️
