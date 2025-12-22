from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import requests
from datetime import datetime
import os
import io
import time
import gspread
import json

app = Flask(__name__)
CORS(app) # Autorise votre futur site web à parler à ce script Python

# --- CONFIGURATION ---
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
GSPREAD_CREDENTIALS_JSON = os.environ.get("GSPREAD_CREDENTIALS")
SPREADSHEET_ID = "VOTRE_ID_GSHEET_ICI" # Pensez à mettre votre ID réel ici

MODE_TRANSPORT = "transit"
BATCH_SIZE = 25
HEURE_DEPART_TIMESTAMP = int(datetime(2025, 12, 1, 8, 0).timestamp())

# --- LOGGING GSHEETS ---
def log_to_google_sheet(data_row):
    if not GSPREAD_CREDENTIALS_JSON: return
    try:
        creds = json.loads(GSPREAD_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.sheet1
        if ws.row_count < 1 or not ws.row_values(1):
            ws.append_row(list(data_row.keys()))
        ws.append_row(list(data_row.values()))
    except Exception as e:
        print(f"Erreur GSheet: {e}")

# --- CALCULS GOOGLE MAPS ---
def get_distances(origine, destinations):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        'origins': origine,
        'destinations': '|'.join(destinations),
        'mode': MODE_TRANSPORT,
        'departure_time': HEURE_DEPART_TIMESTAMP,
        'key': API_KEY
    }
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') != 'OK': return None
        return [el['duration']['value']/60 if el['status'] == 'OK' else None for el in res['rows'][0]['elements']]
    except: return None

# --- ROUTE PRINCIPALE API ---
@app.route("/api/calculate", methods=["POST"])
def calculate():
    # 1. Récupération des données envoyées par le site web
    data = request.form
    file = request.files.get('file')
    
    adresse_actuelle = data.get('adresse_actuelle')
    candidats = [
        {"nom": data.get('nom_1'), "adresse": data.get('adr_1')},
        {"nom": data.get('nom_2'), "adresse": data.get('adr_2')}
    ]
    temps_max = int(data.get('temps_max', 30))

    # 2. Lecture du CSV
    try:
        df = pd.read_csv(file)
        df['dest'] = df['Nom de la voie'].astype(str) + ", " + df['Code postal'].astype(str) + " " + df['Ville'].astype(str) + ", France"
        destinations = df['dest'].tolist()
    except Exception as e:
        return jsonify({"error": f"Erreur CSV: {e}"}), 400

    # 3. Logging
    log_to_google_sheet({
        'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'Entreprise': data.get('entreprise', 'Inconnue'),
        'Candidat_1': candidats[0]['adresse'],
        'Temps_Cible': temps_max
    })

    # 4. Calculs
    final_results = []
    for cand in candidats:
        if not cand['adresse']: continue
        
        all_times = []
        for i in range(0, len(destinations), BATCH_SIZE):
            batch = destinations[i:i+BATCH_SIZE]
            times = get_distances(cand['adresse'], batch)
            if times: all_times.extend(times)
            time.sleep(0.1)
        
        # Statistiques
        df_res = pd.DataFrame({'t': all_times}).dropna()
        moyen = df_res['t'].mean() if not df_res.empty else 0
        couverture = (df_res['t'] <= temps_max).sum() / len(destinations) * 100
        
        final_results.append({
            "nom": cand['nom'],
            "moyen": round(moyen, 1),
            "couverture": round(couverture, 1),
            "adresse": cand['adresse']
        })

    return jsonify(final_results)

# Nécessaire pour Vercel
def handler(request):
    return app(request)
