# GitHub Actions Workflows

This directory contains the CI/CD workflows for the SafeMap project.

## Workflows

### 1. CI (Continuous Integration) - `ci.yml`

**Triggers:**
- Push to `main` or `develop` branches
- Pull requests to `main` or `develop` branches

**What it does:**
- Tests the application on multiple Python versions (3.10, 3.11, 3.12)
- Installs dependencies from `requirements.txt` or `pyproject.toml`
- Runs code quality checks:
  - **Ruff**: Linting and formatting checks
  - **mypy**: Type checking
- Runs tests with pytest and generates coverage reports
- Uploads coverage to Codecov (if configured)
- Builds the application
- Performs security scanning with Bandit

**Usage:**
Simply push code or create a pull request, and the workflow will run automatically.

### 2. CD (Continuous Deployment) - `cd.yml`

**Triggers:**
- When a new release is published
- Manual trigger via GitHub Actions UI

**What it does:**
- Builds the application for deployment
- Creates a deployment artifact
- Uploads the artifact for download
- Can be extended to deploy to various hosting services

**Usage:**
1. **Automatic**: Create a new release on GitHub
2. **Manual**: Go to Actions → CD → Run workflow → Select environment

**Note**: This workflow creates a deployment artifact. You'll need to add specific deployment steps based on your hosting provider (Azure, AWS, Google Cloud, etc.).

### 3. Dependency Updates - `dependency-updates.yml`

**Triggers:**
- Weekly schedule (Mondays at 9:00 AM UTC)
- Manual trigger via GitHub Actions UI

**What it does:**
- Audits dependencies for security vulnerabilities
- Checks for outdated packages
- Generates a dependency report

**Usage:**
Check the workflow runs for security alerts and update recommendations.

### 4. Verify Branch Protection - `verify-protection.yml`

**Triggers:**
- Manual trigger via GitHub Actions UI
- Weekly schedule (Mondays at 9:00 AM UTC)

**What it does:**
- Verifies that branch protection configuration files exist
- Lists the CI jobs that should be required as status checks
- Provides links and instructions for enabling branch protection

**Usage:**
1. **Manual**: Go to Actions → Verify Branch Protection → Run workflow
2. **Automatic**: Runs weekly to remind about branch protection setup

**Note**: This workflow only verifies configuration files. Branch protection must be enabled manually in repository settings or via the Probot Settings app.

## Setup Instructions

### Prerequisites

1. **Python Project Structure**: Your project should have either:
   - `requirements.txt` for dependencies
   - `pyproject.toml` for modern Python projects
   - `setup.py` for older projects

2. **Tests**: Place your tests in a `tests/` directory or name them `test_*.py`

### Recommended Project Structure

```
safemap/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── cd.yml
│       └── dependency-updates.yml
├── src/              # or your application directory
│   └── ...
├── tests/
│   └── test_*.py
├── requirements.txt  # or pyproject.toml
├── requirements-dev.txt  # Optional: dev dependencies
└── README.md
```

### Optional: Configure Codecov

To enable code coverage reports:

1. Sign up at [codecov.io](https://codecov.io)
2. Add your repository
3. Add `CODECOV_TOKEN` to your GitHub repository secrets

### Optional: Configure Deployment Environments

To use the CD workflow with protected environments:

1. Go to your repository Settings → Environments
2. Create environments: `staging` and `production`
3. Add protection rules and secrets as needed

## Customization

### Adjusting Python Versions

Edit the `matrix` section in `ci.yml`:

```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12"]  # Modify as needed
```

### Adding Deployment Steps

Edit `cd.yml` and add your deployment commands. Examples:

**For Azure:**
```yaml
- name: Deploy to Azure
  uses: azure/webapps-deploy@v2
  with:
    app-name: ${{ secrets.AZURE_WEBAPP_NAME }}
    publish-profile: ${{ secrets.AZURE_WEBAPP_PUBLISH_PROFILE }}
```

**For AWS:**
```yaml
- name: Deploy to AWS
  uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: eu-north-1
```

**For Docker:**
```yaml
- name: Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    push: true
    tags: user/app:latest
```

## Troubleshooting

### Workflow not running?

- Check that you've pushed to `main` or `develop` branch
- Verify workflow file syntax at: Actions → Select workflow → View workflow file

### Tests failing?

- Check test output in the workflow run details
- Ensure all dependencies are listed in `requirements.txt` or `pyproject.toml`

### Linting errors?

- Run `ruff check .` locally to see issues
- Run `ruff format .` to auto-format code

## Branch Protection

To ensure code quality and prevent direct pushes to `main`, branch protection should be enabled.

### Required Status Checks

The following CI jobs should be configured as required status checks:
- `build-and-test (3.10)` - Python 3.10 tests
- `build-and-test (3.11)` - Python 3.11 tests
- `build-and-test (3.12)` - Python 3.12 tests
- `security-scan` - Security vulnerability scanning

### How to Enable

**See detailed instructions in [.github/BRANCH_PROTECTION.md](../BRANCH_PROTECTION.md)**

Quick setup:
1. Go to repository **Settings** → **Branches**
2. Add branch protection rule for `main`
3. Enable **"Require status checks to pass before merging"**
4. Select the required status checks listed above
5. Enable **"Require a pull request before merging"** (recommended)
6. Save changes

**Alternative:** Install the [Probot Settings app](https://github.com/apps/settings) to automatically apply the configuration from `.github/settings.yml`

### Verification

Run the "Verify Branch Protection" workflow to check your configuration:
```
Actions → Verify Branch Protection → Run workflow
```

## Security

- The workflows use official GitHub Actions with pinned versions
- Security scanning is performed on every build
- Dependencies are regularly audited
- Consider adding GitHub's Dependabot for automated dependency updates

## Support

For issues with the workflows, check:
- Workflow run logs in the Actions tab
- GitHub Actions documentation: https://docs.github.com/actions
- Project-specific issues in the repository

---

**Note**: These workflows are set up to be flexible and will adapt to your project structure as it grows. Many steps will gracefully skip if certain files or directories don't exist yet.
