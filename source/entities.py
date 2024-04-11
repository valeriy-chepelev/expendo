import requests


def projects(token, org):
    """Return list of project names, up to 1000 projects
    token, org is OAuth credentials"""
    session = requests.Session()
    headers = {"Host": "api.tracker.yandex.net",
               "Authorization": f"OAuth {token}",
               "X-Org-ID": org}
    request = 'https://api.tracker.yandex.net/v2/entities/project/_search'
    params = {'fields': 'summary', 'perPage': '1000'}
    response = session.post(url=request, headers=headers, params=params, data={})
    response.raise_for_status()
    data = response.json()
    return [project['fields']['summary'] for project in data['values']]


def portfolios(token, org):
    """Return list of portfolio names, up to 1000 portfolios
    token, org is OAuth credentials"""
    session = requests.Session()
    headers = {"Host": "api.tracker.yandex.net",
               "Authorization": f"OAuth {token}",
               "X-Org-ID": org}
    request = 'https://api.tracker.yandex.net/v2/entities/portfolio/_search'
    params = {'fields': 'summary', 'perPage': '1000'}
    response = session.post(url=request, headers=headers, params=params, data={})
    response.raise_for_status()
    data = response.json()
    return [project['fields']['summary'] for project in data['values']]
