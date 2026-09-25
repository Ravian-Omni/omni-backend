from src.configs.settings import settings

from .country_data import country_codes


def _get_user_country(country_codes: list[dict[str, str]]) -> dict[str, str]:
    """Get user's country from local settings.

    Args:
        country_codes: List of country code dictionaries.

    Returns:
        Dictionary with country code and name.
    """
    country_code = settings.USER_COUNTRY

    if not country_code:
        return {"code": None, "name": "Unknown"}

    country = next(
        (
            c
            for c in country_codes
            if c["alpha_2"] == country_code or c["alpha_3"] == country_code
        ),
        None,
    )
    return {
        "code": country_code,
        "name": country.get("name") if country else f"Unknown ({country_code})",
    }
