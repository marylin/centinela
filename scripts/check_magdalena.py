from google.cloud import bigquery
client = bigquery.Client(project='centinela-498622')

basin = "Rio Magdalena"

r = list(client.query(f"SELECT basin, municipality, precipitation_mm FROM unified_feeds.rainfall WHERE basin = '{basin}'").result())
print("rainfall:", [(dict(row)["municipality"], dict(row)["precipitation_mm"]) for row in r])

s = list(client.query(f"SELECT basin, municipality, saturation_index FROM unified_feeds.soil_saturation WHERE basin = '{basin}'").result())
print("soil_sat:", [(dict(row)["municipality"], dict(row)["saturation_index"]) for row in s])

mp = list(client.query(f"SELECT basin, municipality FROM unified_feeds.municipality_population WHERE basin = '{basin}'").result())
print("muni_pop:", [(dict(row)["municipality"]) for row in mp])

l = list(client.query("SELECT municipality, slope_angle_deg FROM unified_feeds.landslide WHERE municipality IN ('Neiva', 'Girardot', 'Honda')").result())
print("landslide:", [(dict(row)["municipality"], dict(row)["slope_angle_deg"]) for row in l])

g = list(client.query(f"SELECT basin, river_level_m, alert_threshold_m FROM google_sheets.rapidagent WHERE basin = '{basin}'").result())
print("gauge:", [(dict(row)["river_level_m"], dict(row)["alert_threshold_m"]) for row in g])
