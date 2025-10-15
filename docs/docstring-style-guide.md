# Docstring Style Guide

This project follows **Google-style docstrings** for all Python code.

## Why Google Style?

- Clean and readable
- Widely adopted
- Supported by popular tools (Sphinx, pydoc, VS Code)
- Compatible with black, flake8, and other pre-commit hooks

## Format

### Modules

```python
"""Brief one-line summary of the module.

More detailed description if needed. Can span multiple lines.
Explain the purpose and main functionality.
"""
```

### Classes

```python
class ClassName:
    """Brief description of the class.

    More detailed description if needed.

    Attributes:
        attr1 (type): Description of attr1.
        attr2 (type): Description of attr2.

    Example:
        >>> obj = ClassName()
        >>> obj.method()
    """
```

### Functions/Methods

```python
def function_name(param1: str, param2: int = 0) -> bool:
    """Brief description of what the function does.

    More detailed description if needed. Explain the behavior,
    edge cases, and any important notes.

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 0.

    Returns:
        Description of the return value.

    Raises:
        ValueError: When param1 is invalid.
        KeyError: When required key is missing.

    Example:
        >>> result = function_name("test", 5)
        >>> print(result)
        True

    Note:
        Any important notes about usage.
    """
```

### Async Functions

```python
async def async_function(param: str) -> dict:
    """Brief description.

    Args:
        param: Description.

    Returns:
        Description of returned dict.

    Note:
        This is an async function, use with await.
    """
```

### Properties

```python
@property
def property_name(self) -> str:
    """Brief description of the property.

    Returns:
        Description of the property value.
    """
```

## Rules

1. **Every module** must have a module-level docstring
2. **Every class** must have a docstring
3. **Every public function/method** must have a docstring
4. **Private functions** (_function) should have docstrings if complex
5. Use **imperative mood**: "Return" not "Returns", "Calculate" not "Calculates"
6. First line must be a **brief summary** (one line, ends with period)
7. Add **blank line** after summary if there's more content
8. Use **type hints** in function signatures, not in docstrings (PEP 484)
9. Keep line length under **88 characters** (black standard)

## Sections Order

When applicable, use sections in this order:

1. Summary (one line)
2. Extended description (optional)
3. Args
4. Returns
5. Yields (for generators)
6. Raises
7. Example
8. Note/Warning
9. See Also (for related functions)

## Examples

### Simple Function

```python
def add(a: int, b: int) -> int:
    """Add two numbers together.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b
```

### Complex Function

```python
async def fetch_user_data(
    user_id: str,
    include_posts: bool = False
) -> dict[str, Any]:
    """Fetch user data from the API.

    Retrieves user information from the external API and optionally
    includes their recent posts. Caches results for 5 minutes.

    Args:
        user_id: Unique identifier for the user.
        include_posts: Whether to include user's posts. Defaults to False.

    Returns:
        Dictionary containing:
            - id (str): User ID
            - name (str): User's full name
            - email (str): User's email address
            - posts (list, optional): List of posts if include_posts=True

    Raises:
        ValueError: If user_id is empty or invalid format.
        HTTPError: If API request fails.
        TimeoutError: If request exceeds 30 second timeout.

    Example:
        >>> user = await fetch_user_data("123", include_posts=True)
        >>> print(user["name"])
        John Doe

    Note:
        This function requires VALID_API_KEY environment variable.
        Results are cached for 5 minutes.
    """
```

### Class with Complex Methods

```python
class UserManager:
    """Manage user operations and authentication.

    This class handles all user-related operations including
    creation, authentication, and session management.

    Attributes:
        db_connection: Database connection instance.
        cache: Redis cache for session storage.
        max_attempts: Maximum login attempts before lockout.

    Example:
        >>> manager = UserManager(db_conn, redis_client)
        >>> user = await manager.create_user("john@example.com")
    """

    def __init__(
        self,
        db_connection: Any,
        cache: Any,
        max_attempts: int = 5
    ):
        """Initialize UserManager.

        Args:
            db_connection: Active database connection.
            cache: Redis cache instance.
            max_attempts: Maximum login attempts. Defaults to 5.
        """
        self.db_connection = db_connection
        self.cache = cache
        self.max_attempts = max_attempts

    async def create_user(self, email: str, **kwargs) -> User:
        """Create a new user account.

        Creates user with provided email and optional additional fields.
        Automatically generates secure password hash and verification token.

        Args:
            email: User's email address (must be unique).
            **kwargs: Additional user fields (name, phone, etc.).

        Returns:
            Newly created User instance.

        Raises:
            ValueError: If email format is invalid.
            DuplicateError: If email already exists.
            DatabaseError: If database operation fails.

        Example:
            >>> user = await manager.create_user(
            ...     "john@example.com",
            ...     name="John Doe"
            ... )
        """
```

## What NOT to Do

### ❌ Bad Examples

```python
# Missing docstring
def calculate():
    return 42

# Vague docstring
def process_data(data):
    """Process data."""  # Too vague!

# Wrong format
def get_user(id):
    """
    Gets a user by ID
    @param id: user identifier
    @return: user object
    """  # Wrong style (Javadoc)

# Redundant with type hints
def add(a: int, b: int) -> int:
    """Add numbers.

    Args:
        a (int): First number  # Redundant with type hint
        b (int): Second number
    """
```

### ✅ Good Examples

```python
def calculate() -> int:
    """Calculate the answer to life, universe, and everything.

    Returns:
        The number 42.
    """
    return 42

def process_data(data: list[dict]) -> pd.DataFrame:
    """Transform raw data into cleaned DataFrame.

    Removes duplicates, handles missing values, and normalizes
    column names according to the project style guide.

    Args:
        data: List of dictionaries with raw data records.

    Returns:
        Cleaned and normalized pandas DataFrame.

    Raises:
        ValueError: If data is empty or has invalid structure.
    """

def get_user(user_id: str) -> User | None:
    """Retrieve user by their unique identifier.

    Args:
        user_id: Unique user identifier.

    Returns:
        User object if found, None otherwise.

    Raises:
        DatabaseError: If database query fails.
    """
```

## Tools

### Validate Docstrings

```bash
# Install pydocstyle
pip install pydocstyle

# Check docstrings
pydocstyle src/

# Add to pre-commit (see .pre-commit-config.yaml)
```

### Generate Documentation

```bash
# Install sphinx
pip install sphinx sphinx-rtd-theme

# Initialize
sphinx-quickstart docs

# Generate docs
cd docs && make html
```

## Pre-commit Integration

This style is compatible with:
- ✅ black (code formatter)
- ✅ flake8 (linter)
- ✅ isort (import sorter)
- ✅ pydocstyle (docstring checker)
- ✅ mypy (type checker)

## References

- [PEP 257 - Docstring Conventions](https://peps.python.org/pep-0257/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [NumPy Docstring Guide](https://numpydoc.readthedocs.io/en/latest/format.html)
