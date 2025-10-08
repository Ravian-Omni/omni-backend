from typing import Dict, List

import requests

from .country_data import country_codes


def _get_user_country(country_codes: List[Dict[str, str]]) -> Dict[str, str]:
    """Get user's country from IP address."""
    try:
        response = requests.get("https://ipinfo.io/json", timeout=5)
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
    country = _get_user_country(country_codes)
    print(f"Your country is: {country}")


if __name__ == "__main__":
    main()
