import requests

from src.configs.routes import RoutesConfig

from .country_data import country_codes


def _get_user_country(country_codes: list[dict[str, str]]) -> dict[str, str]:
    """Get user's country from IP address.

    Args:
        country_codes: List of country code dictionaries.

    Returns:
        Dictionary with country code and name.
    """
    try:
        response = requests.get(RoutesConfig.IPINFO_URL, timeout=5)
        response.raise_for_status()

        data = response.json()
        country_code = data.get("country")

        if not country_code:
            return "Unknown (no country code)"

        country = next(
            (
                c
                for c in country_codes
                if c["alpha_2"] == country_code or c["alpha_3"] == country_code
            ),
            None,
        )
        # return country.get("name", "Unknown") if country else f"Unknown ({country_code})"
        return {
            "code": country_code,  # Return the detected code (e.g., "US")
            "name": country.get("name") if country else f"Unknown ({country_code})",
        }
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return "Unknown"
    except ValueError as e:
        print(f"JSON decode error: {e}")
        return "Unknown"
    except Exception as e:
        print(f"Unexpected error: {e}")
        return "Unknown"


def main():
    """Main entry point for country detection demonstration."""
    country = _get_user_country(country_codes)
    print(f"Your country is: {country}")


if __name__ == "__main__":
    main()
