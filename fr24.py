import streamlit as st
import time
import requests
import logging
from math import radians, sin, cos, sqrt, atan2
# Flag to turn logging on or off
ENABLE_LOGGING = True
if ENABLE_LOGGING:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
else:
    logging.basicConfig(level=logging.ERROR)
# Configuration Parameters
API_TOKEN = '01977ba5-1cef-726d-8f2f-8e6511f67088|PcIHECldlGp0bHEvVR47NsPzvKNoXwhthfKrVj7E71e0405e'  # Replace with your actual FR24 API token
CENTER_LAT = -33.7544457  # Latitude for Home
CENTER_LON = 150.9767345  # Longitude for Home
RADIUS_KM = 50  # Radius in kilometers
POLLING_INTERVAL = 5  # Time between API calls in seconds
def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points using the Haversine formula.
    """
    R = 6371.0  # Earth's radius in kilometers
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c
def is_flight_in_circle(flight_lat, flight_lon):
    """
    Check if a flight is within the specified circular area.
    """
    distance = haversine(flight_lat, flight_lon, CENTER_LAT, CENTER_LON)
    return distance <= RADIUS_KM
def send_alert(flight_id):
    """
    Trigger an alert for the flight.
    """
    logging.info(f"Alert: Flight {flight_id} has entered the area.")
def get_flights(bounds):
    """
    Retrieve live flight positions from the FR24 API within the specified bounds.
    """
    url = 'https://fr24api.flightradar24.com/api/live/flight-positions/full'
    headers = {
    'Accept': 'application/json',
        'Accept-Version': 'v1',
        'Authorization': f'Bearer {API_TOKEN}',
    }
    params = {'bounds': bounds}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json().get('data', [])
def monitor_flights():
    """
    Continuously monitor flights and trigger alerts when they enter the circular area.
    """
    alerted_flights = set()
    # Define bounds around the center point (adjust as needed)
    lat_delta = 1.0
    lon_delta = 1.0
    north = CENTER_LAT + lat_delta
    south = CENTER_LAT - lat_delta
    west = CENTER_LON - lon_delta
    east = CENTER_LON + lon_delta
    bounds = f"{north},{south},{west},{east}"
    while True:
        try:
            flights = get_flights(bounds)
            logging.info(f"Retrieved {len(flights)} flights.")
            for flight in flights:
                flight_id = flight.get('fr24_id')
                flight_lat = flight.get('lat')
                flight_lon = flight.get('lon')
                # First, check if the flight has already triggered an alert
                if flight_id in alerted_flights:
                    logging.debug(f"Flight {flight_id} has already been alerted.")
                    continue  # Skip to the next flight
                # Ensure we have the necessary flight data
                if flight_id and flight_lat and flight_lon:
                    # Check if the flight is within the circular area
                    if is_flight_in_circle(flight_lat, flight_lon):
                        send_alert(flight_id)
                        alerted_flights.add(flight_id)
                        logging.info(f"Flight {flight_id} added to alerted flights.")
                    else:
                        logging.debug(f"Flight {flight_id} is outside the area.")
                else:
                    logging.debug(f"Incomplete data for flight {flight_id}. Skipping.")
            # Sleep after processing all flights
            time.sleep(POLLING_INTERVAL)
        except Exception as e:
            logging.error(f"Error: {e}")
            time.sleep(POLLING_INTERVAL)
if __name__ == "__main__":
    monitor_flights()
