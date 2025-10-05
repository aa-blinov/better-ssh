# Contributing to better-ssh

Thank you for considering contributing to better-ssh. This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful and constructive in all interactions. This project aims to provide a welcoming environment for all contributors.

## How to Contribute

### Reporting Bugs

When reporting bugs, please include:

- Operating system and version
- Python version (`python --version`)
- Steps to reproduce the issue
- Expected behavior
- Actual behavior
- Relevant error messages or logs

Use the GitHub issue tracker to submit bug reports.

### Suggesting Features

Feature suggestions are welcome. When proposing a feature:

- Explain the use case and problem it solves
- Describe the proposed solution
- Consider backward compatibility
- Check if similar features already exist or have been proposed

### Contributing Code

#### Development Setup

1. **Fork and Clone**

   ```bash
   git clone https://github.com/aa-blinov/better-ssh.git
   cd better-ssh
   ```

2. **Install Dependencies**

   ```bash
   uv sync
   ```

3. **Create a Branch**

   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

#### Code Standards

**Style Guide:**

- Follow PEP 8
- Use type hints for all function parameters and return values
- Maximum line length: 120 characters (as configured in `.ruff.toml`)
- Use descriptive variable and function names

**Linting and Formatting:**

Before committing, ensure your code passes all checks:

```bash
# Run linter
uv run ruff check app

# Auto-fix issues where possible
uv run ruff check app --fix

# Format code
uv run ruff format app
```

**Documentation:**

- Add docstrings to all public functions and classes
- Use Google-style docstrings
- Update README.md if adding user-facing features
- Include inline comments for complex logic

**Example Docstring:**

```python
def connect(server: Server, copy_password: bool = True) -> int:
    """Connect to SSH server. Returns exit code.
    
    Args:
        server: Server configuration object
        copy_password: Whether to copy password to clipboard
        
    Returns:
        SSH command exit code (0 for success)
    """
```

#### Commit Guidelines

- Write clear, concise commit messages
- Use present tense ("Add feature" not "Added feature")
- Reference issues when applicable (`Fixes #123`)
- Keep commits focused and atomic

**Commit Message Format:**

```
<type>: <subject>

<body (optional)>

<footer (optional)>
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Example:

```
feat: add server group management

- Add group field to Server model
- Implement group filtering in list command
- Update interactive menu to show groups

Closes #45
```

#### Testing

**Manual Testing:**

Test your changes on your platform. If possible, test on multiple platforms:

- Windows 10/11
- macOS
- Linux (Ubuntu/Debian preferred)

**Test Cases:**

- Basic server CRUD operations
- SSH connections with password and key authentication
- Encryption/decryption functionality
- Interactive menu navigation
- Cross-platform path handling
- Error handling and edge cases

**Before Submitting:**

1. Test all modified commands
2. Verify no regressions in existing functionality
3. Check that error messages are clear and helpful
4. Ensure Ctrl+C handling works correctly

#### Pull Request Process

1. **Update Documentation**

   - Update README.md if adding features
   - Add docstrings to new functions
   - Update inline comments if changing logic

2. **Self Review**

   - Review your own code for clarity and correctness
   - Ensure all linting passes
   - Check for any debugging code or console.log statements

3. **Submit PR**

   - Provide a clear description of changes
   - Reference related issues
   - List any breaking changes
   - Include screenshots for UI changes (if applicable)

4. **PR Template**

   ```markdown
   ## Description
   Brief description of changes

   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   - [ ] Documentation update

   ## Testing
   Describe testing performed

   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Self-review completed
   - [ ] Documentation updated
   - [ ] No new warnings or errors
   ```

## Project Structure

```
better-ssh/
├── app/
│   ├── __init__.py
│   ├── cli.py          # CLI commands and Typer app
│   ├── models.py       # Pydantic models
│   ├── storage.py      # JSON storage and config management
│   ├── encryption.py   # Password encryption
│   └── ssh.py          # SSH connection handling
├── pyproject.toml      # Project dependencies
├── .ruff.toml          # Linting configuration
├── .python-version     # Python version
├── README.md
├── LICENSE
└── CONTRIBUTING.md
```

## Architecture Guidelines

**Separation of Concerns:**

- `cli.py`: User interface and command handling
- `models.py`: Data structures
- `storage.py`: Persistence layer
- `encryption.py`: Security operations
- `ssh.py`: External process interaction

**Adding New Commands:**

1. Define command in `cli.py` using `@app.command()`
2. Add proper type hints and docstrings
3. Handle errors gracefully
4. Add Ctrl+C handling with try/except for interactive prompts
5. Update README.md with usage examples

**Adding New Features:**

1. Consider backward compatibility
2. Add settings to `settings.json` if needed
3. Provide migration path for existing users
4. Document breaking changes clearly

## Questions?

If you have questions about contributing:

- Check existing issues and discussions
- Review this document thoroughly
- Open a discussion on GitHub for general questions
- Use issues for specific problems or bugs

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
