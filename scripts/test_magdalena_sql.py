from google.cloud import bigquery

client = bigquery.Client(project="centinela-498622")

with open("sql/risk_score.sql") as f:
    query = f.read()

query = query.replace("'Rio Cauca'", "'Rio Magdalena'")

rows = list(client.query(query).result())
print(f"Got {len(rows)} rows:")
for r in rows:
    d = dict(r)
    print(f"  {d['municipality']}: compound={d.get('compound_score')}, flood={d.get('flood_score')}, landslide={d.get('landslide_score')}, seismic={d.get('seismic_score')}")
