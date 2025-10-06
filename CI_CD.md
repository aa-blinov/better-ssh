# CI/CD Pipeline

## Overview

The project uses GitHub Actions for continuous integration and deployment.

## Workflows

### 1. Tests Workflow (`.github/workflows/tests.yml`)

**Triggers:**
- Push to `master`, `main`, or `develop` branches
- Pull requests to these branches
- Manual trigger via `workflow_dispatch`

**Matrix Testing:**
- **Operating Systems**: Ubuntu, Windows, macOS
- **Python Versions**: 3.12, 3.13

**Steps:**
1. **Checkout code** - Clone repository
2. **Install uv** - Set up uv package manager with caching
3. **Set up Python** - Install specified Python version
4. **Install dependencies** - Run `uv sync --all-extras --dev`
5. **Run linter** - Check code style with ruff
6. **Check formatting** - Verify code formatting
7. **Run tests** - Execute pytest with coverage
8. **Upload coverage** - Send coverage to Codecov (Ubuntu + Python 3.12 only)
9. **Generate summary** - Create test results summary

**Coverage Reporting:**
- Codecov integration for coverage tracking
- Badge generation for README
- XML and terminal reports

### 2. Release Workflow (`.github/workflows/release.yml`)

**Triggers:**
- New release published
- Manual trigger via `workflow_dispatch`

**Jobs:**

#### Build Job
1. Checkout code
2. Install uv
3. Build distribution packages
4. Upload artifacts

#### Publish to PyPI
- **Condition**: Only runs on tags (`refs/tags/*`)
- **Environment**: pypi
- Uses trusted publishing (OIDC)
- Publishes to PyPI automatically

#### GitHub Release Upload
- Downloads built artifacts
- Attaches to GitHub release

## Local Testing

Before pushing, run locally:

```bash
# Run all checks
uv run ruff check app tests
uv run ruff format app tests
uv run pytest --cov=app --cov-report=term-missing

# Or use shorthand
uv run pytest  # Already configured in pytest.ini
```

## Pull Request Checks

All PRs must pass:
- ✅ Linting (ruff check)
- ✅ Formatting (ruff format --check)
- ✅ Tests (pytest)
- ✅ Cross-platform compatibility (Ubuntu, Windows, macOS)
- ✅ Python version compatibility (3.12, 3.13)

## Secrets Configuration

Required secrets for full CI/CD:

### For Coverage (Optional)
- `CODECOV_TOKEN` - Codecov upload token
  - Get from https://codecov.io/
  - Add to GitHub repo secrets

### For PyPI Publishing (When ready)
- Configure trusted publishing on PyPI
- No tokens needed with OIDC

## Status Badges

Add to README:

```markdown
[![Tests](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml/badge.svg)](https://github.com/aa-blinov/better-ssh/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/aa-blinov/better-ssh/branch/master/graph/badge.svg)](https://codecov.io/gh/aa-blinov/better-ssh)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
```

## Troubleshooting

### Tests fail on Windows
- Check line endings (CRLF vs LF)
- Verify path separators in tests

### Coverage upload fails
- Ensure `CODECOV_TOKEN` is set
- Check Codecov project is public or token is valid

### Release workflow doesn't trigger
- Ensure you're creating a GitHub Release (not just a tag)
- Check workflow permissions

## Best Practices

1. **Always test locally first**
   ```bash
   uv run pytest
   uv run ruff check app tests
   ```

2. **Write meaningful commit messages**
   ```bash
   git commit -m "feat: add new feature"
   git commit -m "fix: resolve bug in encryption"
   git commit -m "test: add tests for storage module"
   ```

3. **Keep PRs focused**
   - One feature or fix per PR
   - Include tests for changes
   - Update documentation

4. **Monitor CI results**
   - Check Actions tab after pushing
   - Fix failures promptly
   - Don't merge failing PRs

## Maintenance

### Updating Dependencies

```bash
# Update all dependencies
uv lock --upgrade

# Update specific package
uv add --upgrade pytest

# Commit updated lockfile
git add uv.lock
git commit -m "chore: update dependencies"
```

### Updating GitHub Actions

Check for action updates:
- `actions/checkout@v4` → latest v4
- `astral-sh/setup-uv@v4` → latest
- `codecov/codecov-action@v4` → latest

## Future Enhancements

Possible additions:
- [ ] Docker image building and publishing
- [ ] Documentation generation and deployment
- [ ] Performance benchmarking
- [ ] Security scanning (bandit, safety)
- [ ] Code quality checks (sonarcloud)
