# Hvordan aktivere obligatoriske status-sjekker for main branch

Dette dokumentet forklarer hvordan du konfigurerer GitHub til å kreve at CI-testene skal bestå før kode kan merges til `main` branch.

## Problem

Status-sjekkene fra GitHub Actions vises ikke som obligatoriske når man skal merge en pull request. Vi ønsker at CI-workflowen må fullføres med suksess før det er mulig å merge til `main`.

## Visuell oversikt

```
┌─────────────────────────────────────────────────────────────┐
│                    Pull Request til main                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Status Checks:                                               │
│  ✅ build-and-test (3.10) - Required                         │
│  ✅ build-and-test (3.11) - Required                         │
│  ✅ build-and-test (3.12) - Required                         │
│  ✅ security-scan - Required                                 │
│                                                               │
│  Reviews:                                                     │
│  ✅ 1 approval required                                      │
│                                                               │
│  ┌───────────────────────────────────┐                      │
│  │  [Merge pull request] ✅ ENABLED   │                      │
│  └───────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────┘

Med branch protection aktivert:
❌ Direkte push til main → BLOKKERT
❌ Merge uten godkjenning → BLOKKERT  
❌ Merge med feilende tester → BLOKKERT
✅ Merge med godkjenning + grønne tester → TILLATT
```

## Løsning

Det finnes to måter å konfigurere dette på i GitHub:

### Alternativ 1: Branch Protection Rules (Anbefalt for de fleste)

1. **Gå til repository settings:**
   - Åpne repository på GitHub
   - Klikk på **Settings** (innstillinger)
   - Velg **Branches** i menyen til venstre

2. **Legg til branch protection rule:**
   - Klikk på **Add rule** eller **Add branch protection rule**
   - Under "Branch name pattern", skriv inn: `main`

3. **Konfigurer nødvendige innstillinger:**
   
   ✅ **Aktiver disse innstillingene:**
   - [x] **Require a pull request before merging**
     - [x] Require approvals (minst 1 approval)
     - [x] Dismiss stale pull request approvals when new commits are pushed
   
   - [x] **Require status checks to pass before merging** ⭐ (VIKTIG!)
     - [x] Require branches to be up to date before merging
     - Søk etter og velg følgende status checks:
       - `build-and-test (3.10)`
       - `build-and-test (3.11)`
       - `build-and-test (3.12)`
       - `security-scan`
   
   - [x] **Require conversation resolution before merging** (valgfritt, men anbefalt)
   
   - [ ] **Require signed commits** (valgfritt)
   
   - [ ] **Require linear history** (valgfritt)
   
   - [ ] **Include administrators** (valgfritt - gjelder også for admins)

4. **Lagre innstillingene:**
   - Klikk på **Create** eller **Save changes**

### Alternativ 2: Repository Rulesets (Nyere funksjon)

Repository Rulesets er en nyere og mer fleksibel måte å håndtere branch protection på.

1. **Gå til repository settings:**
   - Åpne repository på GitHub
   - Klikk på **Settings**
   - Velg **Rules** → **Rulesets** i menyen til venstre

2. **Opprett nytt ruleset:**
   - Klikk på **New ruleset** → **New branch ruleset**
   - Gi det et navn, f.eks. "Main Branch Protection"

3. **Konfigurer ruleset:**
   
   **Target branches:**
   - Velg "Add target" → "Include by pattern"
   - Skriv inn: `main`
   
   **Rules:**
   - [x] **Require a pull request before merging**
     - Minimum required approvals: `1`
     - Dismiss stale pull request approvals: ✅
   
   - [x] **Require status checks to pass** ⭐ (VIKTIG!)
     - [x] Require branches to be up to date
     - Legg til status checks:
       - `build-and-test (3.10)`
       - `build-and-test (3.11)`
       - `build-and-test (3.12)`
       - `security-scan`
   
   - [x] **Block force pushes**
   
   - [x] **Require conversation resolution before merging** (valgfritt)

4. **Aktiver ruleset:**
   - Sett "Enforcement status" til **Active**
   - Klikk på **Create**

### Alternativ 3: Bruk Probot Settings App (Automatisk)

Hvis du vil administrere innstillingene via kode:

1. **Installer Probot Settings App:**
   - Gå til https://github.com/apps/settings
   - Klikk på **Install**
   - Velg repository: `MGumpen/safemap`

2. **Konfigurasjonsfilen er allerede opprettet:**
   - Filen `.github/settings.yml` inneholder alle nødvendige innstillinger
   - Probot Settings vil automatisk synkronisere innstillingene når filen endres

## Hvordan det fungerer

Når branch protection er aktivert:

1. **Pull Requests blir påkrevd:**
   - Ingen kan pushe direkte til `main` branch
   - All kode må gå gjennom en pull request

2. **CI må fullføres:**
   - Pull requesten viser status for alle CI-jobber
   - Merge-knappen er deaktivert til alle required checks er grønne ✅
   - Hvis en check feiler ❌, kan man ikke merge før feilen er fikset

3. **Review er påkrevd:**
   - Minst én person må godkjenne pull requesten
   - Reviews blir invalidert hvis ny kode pushes

## Verifisere at det virker

1. **Opprett en test pull request:**
   ```bash
   git checkout -b test-branch-protection
   echo "# Test" >> TEST.md
   git add TEST.md
   git commit -m "Test: Verify branch protection"
   git push origin test-branch-protection
   ```

2. **Sjekk på GitHub:**
   - Åpne pull requesten
   - Du skal se en melding om at status checks må fullføres
   - Merge-knappen skal være deaktivert til alle checks er ferdige
   - Etter at CI er ferdig og grønn, skal du se: 
     - "All checks have passed" ✅
     - Merge-knappen blir aktivert

3. **Test at det ikke er mulig å merge uten status checks:**
   - Hvis du prøver å merge før CI er ferdig, skal du få en feilmelding
   - GitHub skal vise hvilke status checks som mangler

## Status checks som kreves

Følgende CI-jobber må fullføres med suksess:

| Status Check | Beskrivelse |
|-------------|-------------|
| `build-and-test (3.10)` | Bygger og tester på Python 3.10 |
| `build-and-test (3.11)` | Bygger og tester på Python 3.11 |
| `build-and-test (3.12)` | Bygger og tester på Python 3.12 |
| `security-scan` | Sikkerhetsskanning med Bandit |

## Feilsøking

### "Status checks not found"
- Status checks vises bare etter at de har kjørt minst én gang
- Opprett en test pull request for å la CI kjøre
- Etter første kjøring vil status checks dukke opp i listen

### "Cannot merge - Required status checks are failing"
- Dette er forventet! Status checks gjør jobben sin ✅
- Sjekk CI-loggene for å se hva som feilet
- Fiks feilen og push ny kode
- CI vil kjøre på nytt automatisk

### Status checks vises ikke i pull request
- Sjekk at CI-workflowen er konfigurert til å kjøre på pull requests:
  ```yaml
  on:
    pull_request:
      branches: [ main ]
  ```
- Verifiser at `.github/workflows/ci.yml` eksisterer
- Sjekk Actions-fanen for å se om workflowen kjører

## Ytterligere ressurser

- [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub Docs: Managing a branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)
- [GitHub Docs: About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [Probot Settings Documentation](https://github.com/probot/settings)

## Støtte

Hvis du har problemer med å sette opp branch protection, kontakt repository administrator eller sjekk GitHub's dokumentasjon.

---

**Merk:** Branch protection krever GitHub Pro for private repositories, men er gratis for offentlige repositories.
