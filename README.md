# better-ssh

A command-line tool for managing SSH connections with an interactive interface, password management, and optional encryption.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Password Encryption](#password-encryption)
- [Platform Support](#platform-support)
- [Contributing](#contributing)
- [License](#license)

## Overview

better-ssh simplifies SSH connection management by providing an interactive terminal interface for selecting and connecting to servers. It supports password storage with optional SSH key-based encryption, automatic password clipboard integration, and works across Windows, macOS, and Linux.

## Features

- Interactive server selection menu with search capabilities
- Password storage with optional SSH key-based encryption
- Automatic password clipboard integration
- Support for SSH private key authentication
- Server management (add, edit, remove, list)
- Cross-platform compatibility (Windows, macOS, Linux)
- Flexible server identification (by name, partial name, or ID)
- Auto-detection of SSH keys in standard locations

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- SSH client (OpenSSH)

### Steps

1. Clone the repository:

```bash
git clone https://github.com/aa-blinov/better-ssh.git
cd better-ssh
```

2. Install dependencies:

```bash
uv sync
```

3. Verify installation:

```bash
uv run better-ssh --help
```

### SSH Client Installation

The tool requires a system SSH client. Installation instructions vary by platform:

**Windows:**

```powershell
# Via Windows Settings
Settings → Apps → Optional Features → OpenSSH Client

# Via winget
winget install --id Microsoft.OpenSSH.Client -e
```

**macOS:**

SSH client is pre-installed. If needed:

```bash
brew install openssh
```

**Linux:**

```bash
# Ubuntu/Debian
sudo apt install openssh-client

# Fedora/RHEL
sudo dnf install openssh-clients

# Arch Linux
sudo pacman -S openssh
```

## Usage

### Basic Commands

**Interactive menu:**

```bash
uv run better-ssh run
```

**Connect to a server:**

```bash
# With interactive selection
uv run better-ssh connect

# Direct connection by name
uv run better-ssh connect <server-name>
```

**Manage servers:**

```bash
# List all servers
uv run better-ssh list

# Add a new server (interactive)
uv run better-ssh add

# Add with password
uv run better-ssh add --password

# Add with SSH key
uv run better-ssh add --key

# Edit a server
uv run better-ssh edit <server-name>

# Remove a server
uv run better-ssh remove <server-name>
```

**Password management:**

```bash
# Copy password to clipboard
uv run better-ssh copy-pass <server-name>

# Show password (masked)
uv run better-ssh show-pass <server-name>

# Show password (plaintext)
uv run better-ssh show-pass <server-name> --plain
```

### Server Identification

Servers can be identified by:

- Full name (case-insensitive)
- Partial name match
- Server ID (first 8 characters shown in list)

## Configuration

Configuration files are stored in platform-specific directories:

- **Windows:** `%LOCALAPPDATA%\better-ssh\` (typically `C:\Users\username\AppData\Local\better-ssh\`)
- **macOS:** `~/Library/Application Support/better-ssh/`
- **Linux:** `~/.config/better-ssh/`

### Configuration Files

- `servers.json` - Server configurations and encrypted passwords
- `settings.json` - Application settings (encryption status, key source)

## Requirements

- Python 3.12+ (installed automatically via uv)
- System `ssh` client

### Installing SSH Client

**Windows:**

```powershell
# Via Windows Features
Settings → Apps → Optional Features → OpenSSH Client

# Or via winget
winget install --id Microsoft.OpenSSH.Client -e
```

**macOS:**

SSH is pre-installed. If needed:

```bash
brew install openssh
```

**Linux:**

```bash
# Ubuntu/Debian
sudo apt install openssh-client

# Fedora/RHEL
sudo dnf install openssh-clients

# Arch Linux
sudo pacman -S openssh
```

## Password Encryption

By default, passwords are stored in plaintext. The application offers optional encryption using your SSH private key as the encryption key source.

### Enabling Encryption

```bash
# Check encryption status
uv run better-ssh encryption-status

# Enable encryption
uv run better-ssh encrypt

# Disable encryption
uv run better-ssh decrypt
```

### How It Works

The encryption system uses your SSH private key (`~/.ssh/id_ed25519` or `id_rsa`) to derive an encryption key via PBKDF2-HMAC-SHA256 with 100,000 iterations. Passwords are encrypted using Fernet (symmetric encryption) and stored in base64 format.

### Important Considerations

- **Key Dependency:** If you delete or modify your SSH key, encrypted passwords become inaccessible
- **Machine Specific:** Decryption requires the same SSH key on the same machine
- **Backup Recommended:** Back up your SSH key before enabling encryption
- **Automatic Operation:** Passwords are automatically encrypted on save and decrypted on load

### Security Properties

- Passwords remain protected if the `servers.json` file is compromised
- No master password required for daily use
- SSH key protected by operating system file permissions
- Encryption key derived deterministically from SSH key content

## Platform Support

### Supported Operating Systems

- Windows 10/11
- macOS 10.15+
- Linux (any distribution with Python 3.12+)

### Platform-Specific Details

**Configuration Directory:**

- Windows: `%LOCALAPPDATA%\better-ssh\`
- macOS: `~/Library/Application Support/better-ssh/`
- Linux: `~/.config/better-ssh/`

**SSH Key Location:**

All platforms use the standard `~/.ssh/` directory for SSH keys.

**Dependencies:**

All Python dependencies are cross-platform. The only external requirement is a system SSH client, which is typically pre-installed on macOS and Linux.

## Contributing

Contributions are welcome. Please follow these guidelines:

### Reporting Issues

- Check existing issues before creating a new one
- Include your operating system and Python version
- Provide steps to reproduce the problem
- Include relevant error messages or logs

### Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/aa-blinov/better-ssh.git`
3. Create a virtual environment: `uv sync`
4. Create a feature branch: `git checkout -b feature-name`
5. Make your changes

### Code Standards

- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Run linting: `uv run ruff check app`
- Format code: `uv run ruff format app`
- Ensure all checks pass before submitting

### Submitting Changes

1. Commit your changes with clear, descriptive messages
2. Push to your fork
3. Submit a pull request with a description of your changes
4. Ensure all CI checks pass

### Testing

When adding new features:

- Test on multiple platforms if possible
- Verify SSH client compatibility
- Test encryption/decryption functionality
- Check interactive menu behavior

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
