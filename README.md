# Aircraft Shadow Tracker

A Streamlit application that tracks aircraft shadows in real-time and forecasts when shadows will pass over a target location.

## Features

- **Real-time Aircraft Tracking**: Fetches live aircraft data from OpenSky Network or FlightRadar24
- **Shadow Calculation**: Calculates the position of aircraft shadows based on:
  - Aircraft altitude and position
  - Sun position (altitude and azimuth)
  - Time of day
- **Shadow Forecasting**: Predicts future shadow positions based on aircraft velocity and heading
- **Alert System**: Notifies when aircraft shadows will pass within a configurable radius of the target location
- **Visual Map Display**: Interactive map showing:
  - Aircraft positions (blue plane markers)
  - Current shadow positions (green/orange circles)
  - Forecast shadow paths (purple/lightblue lines)
  - Target location with alert radius
- **Alert Logging**: Logs all shadow alerts to CSV with timestamp, callsign, and coordinates
- **Pushover Notifications**: Optional push notifications when alerts are triggered
- **Statistics Dashboard**: Shows aircraft tracked, shadows visible, and active alerts
- **Alert Timeline Visualization**: Interactive chart of historical alerts

## How It Works

1. **Data Collection**: Fetches aircraft data from OpenSky or FlightRadar24 within a configurable bounding box
2. **Sun Position**: Uses pysolar to calculate sun altitude and azimuth for each aircraft position
3. **Shadow Calculation**:
   - Shadow distance = aircraft_altitude / tan(sun_altitude)
   - Shadow bearing = (sun_azimuth + 180°) % 360°
4. **Forecasting**:
   - Projects aircraft position forward based on velocity and heading
   - Recalculates shadow position at each forecast interval
   - Checks if shadow passes within alert radius of target
5. **Alerts**: Triggers when forecasted shadow comes within ALERT_RADIUS_METERS of target

## Configuration

Edit the constants in `app.py`:

```python
TARGET_LAT = -33.7603831919607          # Target latitude
TARGET_LON = 150.971709164045           # Target longitude
RADIUS_KM = 20                          # Search radius for aircraft
FORECAST_INTERVAL_SECONDS = 30          # Forecast time steps
FORECAST_DURATION_MINUTES = 5           # How far ahead to forecast
ALERT_RADIUS_METERS = 50                # Alert trigger distance
```

## Environment Variables

Create a `.env` file with:

```
OPENSKY_USERNAME=your_username
OPENSKY_PASSWORD=your_password
FLIGHTRADAR_API_KEY=your_api_key
PUSHOVER_USER_KEY=your_pushover_user_key
PUSHOVER_API_TOKEN=your_pushover_api_token
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
streamlit run app.py
```

The app will:
- Auto-refresh every 30 seconds
- Display current aircraft and their shadows
- Show forecast paths for the next 5 minutes
- Alert when shadows will pass near the target
- Log alerts to `alert_log.csv`

## Controls

- **Date/Time Selector**: Choose UTC time for shadow calculations
- **Data Source**: Select between OpenSky Network or FlightRadar24
- **Interactive Map**: Zoom and pan to explore different areas

## Output

- **Map Markers**:
  - Red marker: Target location
  - Blue plane icons: Aircraft positions
  - Green/orange circles: Current shadow positions
  - Purple lines: Forecast paths with alerts
  - Light blue lines: Forecast paths without alerts
  - Red circles: Alert points on forecast paths

- **Alerts**: Displayed prominently when shadows will pass near target
- **Statistics**: Aircraft count, shadows visible, active alerts
- **Log**: Historical alert data with visualization

## Technical Details

The shadow calculation uses basic trigonometry and solar position algorithms:
- Sun position calculated using pysolar library
- Haversine formula for distance calculations
- Great circle navigation for position projection
- Assumes flat ground (appropriate for small alert radii)

## License

MIT
