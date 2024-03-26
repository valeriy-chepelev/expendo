import configparser
import requests
from pprint import pprint


def _read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


def projects(token, org):
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
    # return session.get(url='https://api.tracker.yandex.net/v2/entities/project/65e6f2755aa8336acf7799bd?fields=summary', headers=headers, data={})


def portfolios(token, org):
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


if __name__ == '__main__':
    cfg = _read_config('expendo.ini')
    p = portfolios(cfg['token'], cfg['org'])
    pprint(p)
    print('===============')
    p = projects(cfg['token'], cfg['org'])
    pprint(p)
