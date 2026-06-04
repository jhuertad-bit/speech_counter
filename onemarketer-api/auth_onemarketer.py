import logging
import pytz
import hashlib
import requests
from datetime import datetime


def calculate_sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def calculate_login(user, password):
    login_string = f"{user}:{password}"
    return calculate_sha256(login_string)

def calculate_sig(user):
    gmt_minus_3 = pytz.timezone('America/Sao_Paulo')#('Etc/GMT+3')  # GMT-3
    timestamp = datetime.now(gmt_minus_3)
    formatted_time = timestamp.strftime('%Y-%m-%d %H:%M')
    #formatted_time = timestamp.strftime('%Y-%m-%d')
    #formatted_time = '2025-06-23 17:48'
    sig_string = f"day={formatted_time}&user={user}"
    print(sig_string)
    return calculate_sha256(sig_string)

def calculate_x_signature(login, sig):
    signature_string = f"login={login}&sig={sig}"
    return calculate_sha256(signature_string)

USER = 'utppregradoapi'
PASS = 'utppregradoOM.2O2S'

login = calculate_login(USER, PASS)
print(f'logging: {login}')
sig = calculate_sig(USER)
print(f'sig: {sig}')
x_signature = calculate_x_signature(login, sig)
print(x_signature)
oauth_endpoint = 'https://utp.onemarketer.cl/utp_pregrado/oauth'

curl_command = f"""curl --location '{oauth_endpoint}' \\
--header 'X-Signature: {x_signature}' \\
--header 'Content-Type: application/x-www-form-urlencoded' \\
--data-urlencode 'login={login}' \\
--data-urlencode 'sig={sig}'"""

print(curl_command)


headers = {
    'X-Signature': x_signature,
    'Content-Type': 'application/x-www-form-urlencoded'
}
data = {
    'login': login,
    'sig': sig
}

response = requests.post(oauth_endpoint, headers=headers, data=data)

# Imprimir la respuesta
print(response.status_code)
print(response.text)