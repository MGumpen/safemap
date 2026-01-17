# Quick Setup Guide: Branch Protection

## Problem
Status checks ikke vises som obligatoriske i pull requests til `main` branch.

## Solution (3 steg)

### Steg 1: Gå til Settings
```
https://github.com/MGumpen/safemap/settings/branches
```

### Steg 2: Add Branch Protection Rule
1. Klikk **"Add rule"**
2. Branch name pattern: `main`

### Steg 3: Enable Required Settings
Aktiver disse boksene:

#### ✅ Require a pull request before merging
- Require approvals: `1`
- Dismiss stale pull request approvals when new commits are pushed

#### ✅ Require status checks to pass before merging ⭐ VIKTIG!
- Require branches to be up to date before merging
- Søk og velg disse status checks:
  - `build-and-test (3.10)`
  - `build-and-test (3.11)`
  - `build-and-test (3.12)`
  - `security-scan`

**Viktig:** Status checks vises bare i listen etter at CI har kjørt minst én gang. Opprett en test PR først hvis de ikke vises.

#### ✅ Require conversation resolution before merging (valgfritt)

### Steg 4: Lagre
Klikk **"Create"** eller **"Save changes"**

## Resultat

Når aktivert:
- ❌ Ingen direktepush til `main`
- ✅ PR er påkrevd
- ✅ Alle CI-tester må være grønne
- ✅ Minst 1 godkjenning påkrevd
- ✅ Merge-knappen deaktivert til alt er OK

## Detaljert Dokumentasjon
Se [BRANCH_PROTECTION.md](BRANCH_PROTECTION.md) for fullstendig guide.

## Alternativ: Automatisk via Probot
1. Installer: https://github.com/apps/settings
2. Konfigurasjonen i `.github/settings.yml` vil synkroniseres automatisk

---

## Visuell Flyt

```
Developer → Feature Branch → Pull Request → CI Runs
                                    ↓
                              Status Checks
                              ✅ build-and-test (3.10)
                              ✅ build-and-test (3.11)
                              ✅ build-and-test (3.12)
                              ✅ security-scan
                                    ↓
                              ✅ Code Review
                                    ↓
                              [Merge] → main branch
```
