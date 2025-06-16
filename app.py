import os
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv('OPENSKY_USERNAME')
PASSWORD = os.getenv('OPENSKY_PASSWORD')

import requests
url = "https://opensky-network.org/api/states/all"
r = requests.get(url, auth=(USERNAME, PASSWORD))
data = r.json()
print(data)