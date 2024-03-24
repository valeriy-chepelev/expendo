import requests
import json
from pprint import pprint


def get_ent(token, org):
    session = requests.Session()
    headers = {"Host": "api.tracker.yandex.net",
               "Authorization": f"OAuth {token}",
               "X-Org-ID": org}
    return session.post(url='https://api.tracker.yandex.net/v2/entities/project/_search', headers=headers, data={})

d = get_ent('', '')
j = json.loads(d.text)
pprint(j)