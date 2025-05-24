import json
import os

CREDENTIALS_FILE = 'credentials.rta'
USERDATA_FILE = 'userData.rta'
TRANSACTIONS_FILE = 'transactions.rta'
PENDING_FILE = 'toConfirm.rta'

def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default
    return default

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

def load():
    userCredentials = load_json(CREDENTIALS_FILE, {})
    toConfirmTransaction = load_json(PENDING_FILE, [])
    transactions = load_json(TRANSACTIONS_FILE, [])
    userData = load_json(USERDATA_FILE, {})

    return userCredentials, toConfirmTransaction, transactions, userData

def save(userCredentials, toConfirmTransaction, transactions, userData):
    save_json(CREDENTIALS_FILE, userCredentials)
    save_json(PENDING_FILE, toConfirmTransaction)
    save_json(TRANSACTIONS_FILE, transactions)
    save_json(USERDATA_FILE, userData)
