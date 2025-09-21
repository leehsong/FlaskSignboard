import requests

url = "http://localhost:5000/api/company/signboards"
params = {"emd": "당리동", "company": "늘봄광고기획", "limit": 5, "sb_limit": 20}
r = requests.get(url, params=params, headers={"Accept": "application/json; charset=utf-8"})
print(r.status_code)
print(r.json())