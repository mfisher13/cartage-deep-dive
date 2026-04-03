from flask import Flask, request, render_template
import pandas as pd
import requests

app = Flask(__name__)

# CONFIG
ORS_API_KEY = "PASTE_YOUR_API_KEY_HERE"
AVG_SPEED_MPH = 30
TRAFFIC_MULTIPLIER = 1.25
STOP_TIME_MIN = 15

# -------------------------
# GEO + ROUTING
# -------------------------
geo_cache = {}

def geocode_address(address):
    url = "https://api.openrouteservice.org/geocode/search"

    params = {
        "api_key": ORS_API_KEY,
        "text": address,
        "size": 1
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()
        if data['features']:
            return data['features'][0]['geometry']['coordinates']

    return None

def get_coords(address):
    if address in geo_cache:
        return geo_cache[address]

    coords = geocode_address(address)
    if coords:
        geo_cache[address] = coords

    return coords

def optimize_route(addresses):
    locations = []

    for addr in addresses:
        coords = get_coords(addr)
        if coords:
            locations.append(coords)

    if len(locations) < 2:
        return None, None

    url = "https://api.openrouteservice.org/v2/directions/driving-car"

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }

    body = {
        "coordinates": locations,
        "optimize_waypoints": True
    }

    response = requests.post(url, json=body, headers=headers)

    if response.status_code == 200:
        data = response.json()
        summary = data['routes'][0]['summary']

        distance_miles = summary['distance'] * 0.000621371
        duration_hours = summary['duration'] / 3600

        return distance_miles, duration_hours

    return None, None


# -------------------------
# MAIN ROUTE
# -------------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    kpis = {}
    drivers = []
    lanes = []
    trend = []

    if request.method == 'POST':
        files = request.files.getlist('files')
        hourly_wage = float(request.form.get('wage', 25))
        truck_cost = float(request.form.get('truck_cost', 400))
        stop_time = float(request.form.get('stop_time', STOP_TIME_MIN))

        df_list = []

        for file in files:
            df = pd.read_csv(file)
            df.columns = df.columns.str.strip()
            df_list.append(df)

        df = pd.concat(df_list)

        df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
        df['Date'] = pd.to_datetime(df['Date'])

        grouped = df.groupby(['Driver', 'Date'])

        output = []

        for (driver, date), group in grouped:
            total_weight = group['Weight'].sum()
            stops = len(group)

            addresses = list(dict.fromkeys(group['Addy'].dropna().tolist()))

            optimized_miles, optimized_drive_hours = optimize_route(addresses)

            if not optimized_miles:
                optimized_miles = stops * 5
                optimized_drive_hours = optimized_miles / AVG_SPEED_MPH

            optimized_drive_hours *= TRAFFIC_MULTIPLIER

            stop_time_hours = (stops * stop_time) / 60
            optimized_total_hours = optimized_drive_hours + stop_time_hours

            actual_hours = group['HoursWorked'].iloc[0] if 'HoursWorked' in group else None

            labor_cost = (actual_hours if actual_hours else optimized_total_hours) * hourly_wage
            total_cost = labor_cost + truck_cost

            cost_per_lb = total_cost / total_weight if total_weight else 0

            time_saved = (actual_hours - optimized_total_hours) if actual_hours else 0
            cost_saved = time_saved * hourly_wage if time_saved > 0 else 0

            output.append({
                "Driver": driver,
                "Date": date.date(),
                "Stops": stops,
                "Weight": round(total_weight, 2),
                "Est Hours": round(optimized_total_hours, 2),
                "Actual Hours": actual_hours,
                "Cost": round(total_cost, 2),
                "Cost/LB": round(cost_per_lb, 3),
                "Opt Hours": round(optimized_total_hours, 2),
                "Time Saved": round(time_saved, 2),
                "Cost Saved": round(cost_saved, 2)
            })

        df_results = pd.DataFrame(output)

        # KPIs
        kpis = {
            "total_weight": df_results["Weight"].sum(),
            "total_cost": df_results["Cost"].sum(),
            "avg_cost_lb": df_results["Cost"].sum() / df_results["Weight"].sum() if df_results["Weight"].sum() else 0,
            "total_stops": df_results["Stops"].sum(),
            "total_savings": df_results["Cost Saved"].sum()
        }

        # Driver Scorecard
        driver_summary = df_results.groupby("Driver").agg({
            "Weight": "sum",
            "Cost": "sum",
            "Stops": "sum",
            "Time Saved": "sum"
        }).reset_index()

        driver_summary["Cost/LB"] = driver_summary["Cost"] / driver_summary["Weight"]

        # Trend
        trend_df = df_results.groupby("Date").agg({
            "Cost": "sum",
            "Weight": "sum"
        }).reset_index()

        trend_df["Cost/LB"] = trend_df["Cost"] / trend_df["Weight"]

        results = df_results.to_dict(orient='records')
        drivers = driver_summary.to_dict(orient='records')
        trend = trend_df.to_dict(orient='records')

    return render_template(
        'index.html',
        results=results,
        kpis=kpis,
        drivers=drivers,
        trend=trend
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=81)
