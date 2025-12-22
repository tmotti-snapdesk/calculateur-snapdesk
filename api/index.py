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
CORS(app)

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
GSPREAD_CREDENTIALS_JSON = os.environ.get("GSPREAD_CREDENTIALS")
SPREADSHEET_ID = "16CmT1OMabFmJzXNKNU4qbsu1-8Jy37RQAUcWn1KhmYE"

MODE_TRANSPORT = "transit"
BATCH_SIZE = 25
HEURE_DEPART_TIMESTAMP = int(datetime(2025, 12, 1, 8, 0).timestamp())

def log_to_google_sheet(data_log):
    if not GSPREAD_CREDENTIALS_JSON: return
    try:
        creds = json.loads(GSPREAD_CREDENTIALS_JSON)
        gc = gspread.service_account_from_dict(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.sheet1
        if ws.row_count < 1 or not ws.row_values(1):
            ws.append_row(list(data_log.keys()))
        ws.append_row(list(data_log.values()))
    except Exception as e:
        print(f"Erreur GSheet: {e}")

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
        # Cette ligne permet de voir enfin pourquoi Google refuse dans les logs Vercel
        print(f"DEBUG MAPS: {res.get('status')} - {res.get('error_message', '')}")
        
        if res.get('status') != 'OK': 
            return [None] * len(destinations)
        
        return [el['duration']['value']/60 if el.get('status') == 'OK' else None for el in res['rows'][0]['elements']]
    except Exception as e:
        print(f"ERREUR REQUETE: {e}")
        return [None] * len(destinations)
        
@app.route("/api/calculate", methods=["POST"])
def calculate():
    data = request.form
    user_email = data.get('email', 'Non renseigné')
    
    # Récupération des adresses (CSV ou Manuel)
    destinations = []
    file = request.files.get('file')
    manual_addresses = data.get('manual_addresses', '')

    if file:
        try:
            df = pd.read_csv(file)
            destinations = (df['Nom de la voie'].astype(str) + ", " + df['Code postal'].astype(str) + " " + df['Ville'].astype(str)).tolist()
        except: pass
    elif manual_addresses:
        destinations = [a.strip() for a in manual_addresses.split('\n') if len(a.strip()) > 5]

    if not destinations:
        return jsonify({"error": "Aucune adresse de collaborateur trouvée."}), 400

    candidats = []
    if data.get('adr_1'): candidats.append({"nom": data.get('nom_1', 'Candidat 1'), "adr": data.get('adr_1')})
    if data.get('adr_2'): candidats.append({"nom": data.get('nom_2', 'Candidat 2'), "adr": data.get('adr_2')})

    # Logging
    log_to_google_sheet({
        'Timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'Email': user_email,
        'Nb_Collabs': len(destinations),
        'Bureau_1': data.get('adr_1'),
        'Bureau_2': data.get('adr_2')
    })

    results = []
    for cand in candidats:
        all_times = []
        for i in range(0, len(destinations), BATCH_SIZE):
            batch = destinations[i:i+BATCH_SIZE]
            t = get_distances(cand['adr'], batch)
            if t: all_times.extend(t)
        
        df_res = pd.DataFrame({'t': all_times}).dropna()
        moyen = df_res['t'].mean() if not df_res.empty else 0
        
        # Calcul des deux seuils
        couv_30 = (df_res['t'] <= 30).sum() / len(destinations) * 100
        couv_45 = (df_res['t'] <= 45).sum() / len(destinations) * 100
        
        results.append({
            "nom": cand['nom'], 
            "moyen": round(moyen, 1), 
            "couv_30": round(couv_30, 1),
            "couv_45": round(couv_45, 1)
        })

    return jsonify(results)

app = app
