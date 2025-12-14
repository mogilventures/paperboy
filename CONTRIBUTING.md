# Contributing to Paperboy

Thank you for considering contributing to Paperboy.

## Code of Conduct

By participating in this project, you are expected to uphold our Code of Conduct. Please report unacceptable behavior to the project maintainers.

## How to Contribute

### Reporting Bugs

- Check whether the issue has already been reported
- Include steps to reproduce
- Include expected vs actual behavior
- Include system info (OS, Python version, etc.)

### Suggesting Features

- Describe the feature and why it’s valuable
- Provide examples of expected behavior if possible

### Pull Requests

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Run tests: `pytest`
4. Commit with descriptive messages
5. Push your branch and open a PR

## Development Environment

### Setup

1. Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.lightweight.txt
```

3. Copy the example environment file:

```bash
cp config/.env.example config/.env
```

4. Edit `config/.env` with required keys and settings.

### Docker Development

```bash
docker-compose up --build
```

## Coding Guidelines

- Follow PEP 8
- Add docstrings for public functions/classes
- Add type hints
- Add tests for new functionality
- Keep functions small and focused

## Testing

```bash
pytest
```

## Documentation

- Update `README.md` if you change usage/setup
- Update API docs if you modify endpoints

## License

By contributing to this project, you agree that your contributions will be licensed under the project’s MIT License.
