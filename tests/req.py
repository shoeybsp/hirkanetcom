import json
import requests

uinput = input("Enter a URL: ").strip()

if not uinput.startswith(("http://", "https://")):
    uinput = "https://" + uinput

try:
    response = requests.get(
        uinput,
        timeout=15,
        allow_redirects=True,
    )

    response.raise_for_status()

    print("Final URL:", response.url)
    print("Status code:", response.status_code)

    print("\nResponse headers:")
    print(json.dumps(dict(response.headers), indent=4))

except requests.exceptions.MissingSchema:
    print("Invalid URL: include http:// or https://")

except requests.exceptions.ConnectionError:
    print("Could not connect to the server.")

except requests.exceptions.Timeout:
    print("The request timed out.")

except requests.exceptions.HTTPError as error:
    print("HTTP error:", error)

except requests.exceptions.RequestException as error:
    print("Request failed:", error)