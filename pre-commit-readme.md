# Pre-commit Hooks Setup Guide

This guide will help you set up and use pre-commit hooks for the FastAPI project to maintain code quality and security.

## 📋 What Are Pre-commit Hooks?

Pre-commit hooks automatically check your code before you commit it to Git. They help:
- Remove unused imports and variables
- Format code consistently
- Catch bugs and security issues early
- Enforce coding standards across the team

## 🚀 Quick Start

### 1. Install Pre-commit

```bash
pip install pre-commit
```

### 2. Install the Hooks

Navigate to your project root (where `.pre-commit-config.yaml` is located) and run:

```bash
pre-commit install
```

This installs the git hook scripts that will run automatically on `git commit`.

### 3. (Optional) Run on All Files

To run the hooks on all files in your repository:

```bash
pre-commit run --all-files
```

## ✅ What Hooks Are Included?

### Core Code Quality Hooks

| Hook | Purpose | What It Does |
|------|---------|--------------|
| **autoflake** | Remove unused code | Deletes unused imports, variables, and duplicate keys |
| **isort** | Organize imports | Sorts imports alphabetically and by type (stdlib, third-party, local) |
| **black** | Format code | Auto-formats Python code to PEP 8 standard |
| **flake8** | Lint code | Finds bugs, style issues, and complexity problems |

### Security Hooks

| Hook | Purpose | What It Does |
|------|---------|--------------|
| **bandit** | Security scanner | Detects SQL injection, hardcoded passwords, and other vulnerabilities |
| **detect-secrets** | Secret detection | Prevents committing API keys, tokens, and credentials |

### Utility Hooks

| Hook | Purpose | What It Does |
|------|---------|--------------|
| **pre-commit-hooks** | File checks | Trims whitespace, checks YAML/JSON syntax, detects merge conflicts |
| **pyupgrade** | Modernize syntax | Converts old Python syntax to modern Python 3.12+ features |
| **pygrep-hooks** | Anti-patterns | Catches deprecated patterns like `eval()` usage |

## 🔧 Configuration Details

### Line Length
- Maximum line length: **588 characters** (very permissive)
- Line length checking is **disabled** (E501 ignored)

### Complexity
- Maximum function complexity: **20** (allows moderately complex functions)
- Complexity warnings **disabled** (C901 ignored)

### Security Exceptions
The following security warnings are skipped:
- **B101**: Assert statements
- **B601**: Shell injection (paramiko)
- **B324**: MD5 hash usage (safe for checksums)
- **B104**: Binding to 0.0.0.0 (normal for web servers)

### Excluded Files
These files/directories are automatically excluded from all checks:
- `migrations/` - Database migrations
- `__pycache__/`, `*.pyc`, `*.pyo` - Python cache files
- `.venv/`, `venv/`, `env/` - Virtual environments
- `build/`, `dist/` - Build artifacts
- `prompts.py` - Prompt configuration files
- `build_scripts/`, `scripts/` - Build and utility scripts
- `*.sh` - Shell scripts
- `*.md` - Markdown files (for detect-secrets)

## 💻 Daily Usage

### Normal Workflow

When you commit code, pre-commit hooks run automatically:

```bash
git add .
git commit -m "Your commit message"
```

If any hook fails, your commit will be blocked and you'll see what needs to be fixed.

### Skipping Hooks (When Needed)

If you need to skip hooks temporarily:

```bash
# Skip all hooks
git commit --no-verify -m "Emergency fix"

# Skip specific hooks
SKIP=bandit,detect-secrets git commit -m "Skip security checks"
```

**⚠️ Warning:** Only skip hooks when absolutely necessary!

### Running Specific Hooks

Test individual hooks before committing:

```bash
# Run a specific hook
pre-commit run autoflake --all-files
pre-commit run black --all-files
pre-commit run flake8 --all-files

# Run on staged files only
pre-commit run
```

## 🔄 Updating Hooks

Keep hooks up-to-date with the latest versions:

```bash
pre-commit autoupdate
```

This updates all hook versions in `.pre-commit-config.yaml`.

## 🐛 Troubleshooting

### Hook Fails on First Run

On the first run, pre-commit needs to install hook environments. This is normal and takes a few minutes.

### Cache Issues

If you encounter strange errors:

```bash
# Clear pre-commit cache
rm -rf ~/.cache/pre-commit

# Reinstall hooks
pre-commit clean
pre-commit install

# Try again
pre-commit run --all-files
```

### Detect-Secrets Issues

If detect-secrets complains about missing plugins:

```bash
# Delete old baseline
rm .secrets.baseline

# Update to latest version
pre-commit autoupdate

# Create fresh baseline
detect-secrets scan > .secrets.baseline
```

### Excluding More Files

Edit `.pre-commit-config.yaml` and add patterns to the global `exclude` section or individual hook `exclude` sections.

Example:
```yaml
exclude: |
  (?x)^(
      your_file\.py|
      your_directory/.*
  )$
```

## 📊 Hook Performance

Typical run times on a medium-sized project:
- **autoflake**: ~2 seconds
- **isort**: ~1 second
- **black**: ~3 seconds
- **flake8**: ~5 seconds
- **bandit**: ~8 seconds
- **detect-secrets**: ~4 seconds

Total: ~25 seconds for all hooks

## 🎯 Best Practices

1. **Run hooks before pushing**: `pre-commit run --all-files`
2. **Don't skip hooks without reason**: They catch real issues
3. **Keep hooks updated**: Run `pre-commit autoupdate` monthly
4. **Fix issues, don't ignore them**: Use exclusions sparingly
5. **Commit hook fixes separately**: Makes review easier

## 🆘 Getting Help

### Common Commands

```bash
# Show installed hooks
pre-commit run --help

# Run hooks in verbose mode
pre-commit run --verbose --all-files

# Run hooks on specific files
pre-commit run --files file1.py file2.py

# Uninstall hooks (if needed)
pre-commit uninstall
```

### Resources

- [Pre-commit Documentation](https://pre-commit.com/)
- [Black Documentation](https://black.readthedocs.io/)
- [Flake8 Documentation](https://flake8.pycqa.org/)
- [Bandit Documentation](https://bandit.readthedocs.io/)

## 📝 Team Guidelines

### For New Team Members

1. Clone the repository
2. Run `pip install pre-commit`
3. Run `pre-commit install`
4. Make your first commit - hooks will run automatically!

### For Code Reviewers

If a PR has formatting issues:
```bash
# Reviewer can fix formatting locally
git checkout pr-branch
pre-commit run --all-files
git commit -am "Apply pre-commit fixes"
git push
```

### Continuous Integration

Add this to your CI pipeline (`.github/workflows/ci.yml`):

```yaml
- name: Run pre-commit
  run: |
    pip install pre-commit
    pre-commit run --all-files
```

## 🎉 Success!

You're all set! Pre-commit hooks will now automatically maintain code quality and catch issues before they reach your repository.

Happy coding! 🚀
