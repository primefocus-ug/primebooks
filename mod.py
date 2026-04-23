import uuid
import requests

base_url = "https://sandbox.momodeveloper.mtn.com"

refe= str(uuid.uuid4())

headers = {
    "X-Reference-Id": refe,
    "Content-Type": "application/json",
    "Ocp-Apim-Subscription-Key": "0f894d0b9cb24ddb8652aa2ffa9cb470"
}

body = {
    "providerCallbackHost": "yourdomain.com"
}

req = requests.post(
    f"{base_url}/v1_0/apiuser",
    headers=headers,
    json=body
)

print(req.status_code)
print(req.text)

reqq=requests.get(f"{base_url}/v1_0/apiuser/{refe}",json=headers)
print(reqq.text)