from yandex_tracker_client import TrackerClient
import datetime as dt
from dateutil.rrule import rrule, DAILY
import math
from functools import lru_cache
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import configparser

# g_project = "MT SystemeLogic(ACB)"  # Temporary, will be moved to argument parser
# g_project = "MT БМРЗ-60"  # Temporary, will be moved to argument parser
g_project = "MT Дуга-О3"  # Temporary, will be moved to argument parser


def read_config():
    config = configparser.ConfigParser()
    config.read('expendo.ini')
    assert 'token' in config['DEFAULT']
    assert 'org' in config['DEFAULT']
    return config['DEFAULT']


def _get_iso_split(s, split):
    """ Splitter helper for converting ISO dt notation"""
    if split in s:
        n, s = s.split(split)
    else:
        n = 0
    if n == '':
        n = 0
    return int(n), s


def iso_hrs(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored."""
    if s is None:
        return 0
    # Remove prefix
    s = s.split('P')[-1]
    # Step through letter dividers
    weeks, s = _get_iso_split(s, 'W')
    days, s = _get_iso_split(s, 'D')
    _, s = _get_iso_split(s, 'T')
    hours, s = _get_iso_split(s, 'H')
    # Convert all to hours
    return (weeks * 5 + days) * 8 + hours


def iso_days(s):
    """ Convert ISO dt notation to hours.
    Mean 8 hours per day, 5 day per week.
    Values except Weeks, Days, Hours ignored.
    Hours less than 8 rounded up to 1 day."""
    return math.ceil(iso_hrs(s) / 8)


def epics(client, project):
    """ Return list of all project epics """
    request = f'Project: "{project}" Type: "Epic" "Sort by": Created ASC'
    return client.issues.find(query=request)


def stories(client, project):
    """ Return list of first-level project stories"""
    request = f'Project: "{project}" Type: "Story" "Sort by": Created ASC'
    return [st for st in client.issues.find(query=request)
            if (e := st.parent) is not None and e.type.key == 'epic']


def history_estimate(issues: list, by_component=False):
    """ Return historical issues estimates daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    keys = [issue.key for issue in issues]
    estimates = [{'key': issue.key,
                  'components': cashed_components(issue),
                  'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
                  'estimate': 0 if field['to'] is None else iso_days(field['to'])}
                 for issue in issues for log in issue.changelog for field in log.fields
                 if field['field'].id == 'estimation']
    if len(estimates) == 0:
        return {dt.datetime.now(dt.timezone.utc).date(): {key: 0 for key in keys}}
    # sort by date reversed
    estimates.sort(key=lambda d: d['date'], reverse=True)
    # get first estimate date (in reverse sort it's a last value)
    start_date = estimates[-1]['date']
    # convert to 2-d table day-by day for different tickets
    if by_component:
        return {date.date(): {component: sum(
            [next((e['estimate'] for e in estimates
                   if e['key'] == key and e['date'].date() <= date.date() and
                   component in e['components']), 0)
             for key in keys])
            for component in components(issues)}
            for date in rrule(DAILY, dtstart=start_date, until=dt.datetime.now(dt.timezone.utc))}
    return {date.date(): {key: next((e['estimate'] for e in estimates
                                     if e['key'] == key and e['date'].date() <= date.date()), 0)
                          for key in keys}
            for date in rrule(DAILY, dtstart=start_date, until=dt.datetime.now(dt.timezone.utc))}


def components(issues: list):
    """ Return list of components assigned to issues """
    return sorted(list({comp.name for issue in issues for comp in issue.components}))


@lru_cache(maxsize=None)  # Cashing access to YT
def cashed_components(issue):
    """ Return one issue components """
    return components([issue])


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_issue_times(issue):
    """ Return reverse-sorted list of issue spent and estimates """
    sp = [{'date': dt.datetime.strptime(log.updatedAt, '%Y-%m-%dT%H:%M:%S.%f%z'),
           'kind': field['field'].id,
           'value': 0 if (v := field['to']) is None else iso_hrs(v)}
          for log in issue.changelog for field in log.fields
          if field['field'].id in ['spent', 'estimation']]
    sp.sort(key=lambda d: d['date'], reverse=True)
    return sp


@lru_cache(maxsize=None)  # Cashing access to YT
def _get_linked(issue):
    """ Return list of issue linked subtasks """
    return [link.object for link in issue.links
            if link.type.id == 'subtask' and
            dict(outward=link.type.inward, inward=link.type.outward)[link.direction] == 'Подзадача']


def issue_spent(issue, date, component='', default_comp=()):
    """ Return summary spent of issue (hours) including spent of all child issues,
    due to the date, containing specified component."""
    own_comp = cashed_components(issue)
    sp = 0
    if component == '' or component in own_comp or \
            (len(own_comp) == 0 and component in default_comp):
        spends = _get_issue_times(issue)
        sp = next((s['value'] for s in spends
                   if s['kind'] == 'spent' and s['date'].date() <= date.date()), 0) + \
            sum([issue_spent(linked, date, component, own_comp if len(own_comp) > 0 else default_comp)
                 for linked in _get_linked(issue)])
    return sp


def issue_estimate(issue, date, component='', default_comp=()):
    """ Return estimate of issue (hours) as summary estimates of all child issues,
    for the date, containing specified component."""
    own_comp = cashed_components(issue)
    est = 0
    if component == '' or component in own_comp or \
            (len(own_comp) == 0 and component in default_comp):
        if len(_get_linked(issue)) == 0:
            estimates = _get_issue_times(issue)
            est = next((s['value'] for s in estimates
                        if s['kind'] == 'estimation' and s['date'].date() <= date.date()), 0)
        else:
            est = sum([issue_estimate(linked, date, component, own_comp if len(own_comp) > 0 else default_comp)
                       for linked in _get_linked(issue)])
    return est


def spent(issues: list, by_component=False):
    """ Return issues summary spent daily timeline as dictionary of
    {date: {issue_key: spent[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    if by_component:
        all_components = components(issues)
        return {date.date(): {component: sum([issue_spent(issue, date, component)
                                              for issue in issues]) // 8  # hours to days
                              for component in all_components}
                for date in rrule(DAILY, dtstart=get_start_date(issues),
                                  until=dt.datetime.now(dt.timezone.utc))}
    return {date.date(): {issue.key: issue_spent(issue, date) // 8  # hours to days
                          for issue in issues}
            for date in rrule(DAILY, dtstart=get_start_date(issues),
                              until=dt.datetime.now(dt.timezone.utc))}


def estimate(issues: list, by_component=False):
    """ Return issues estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    if by_component:
        all_components = components(issues)
        return {date.date(): {component: sum([issue_estimate(issue, date, component)
                                              for issue in issues]) // 8  # hours to days
                              for component in all_components}
                for date in rrule(DAILY, dtstart=get_start_date(issues),
                                  until=dt.datetime.now(dt.timezone.utc))}
    return {date.date(): {issue.key: issue_estimate(issue, date) // 8  # hours to days
                          for issue in issues}
            for date in rrule(DAILY, dtstart=get_start_date(issues),
                              until=dt.datetime.now(dt.timezone.utc))}


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    try:
        return min([t[-1]['date'] for issue in issues
                    if len(t := _get_issue_times(issue)) > 0])
    except ValueError:
        return dt.datetime.now(dt.timezone.utc)


# Data output routines


def tabulate_summary(d: dict):
    print('Date;Summary')
    for date in d.keys():
        print(f'{date.strftime("%d.%m.%y")};{sum(d[date].values())}')


def plot_summary(title: str, d: dict):
    fig, ax = plt.subplots()
    ax.plot([date for date in d.keys()],
            [sum(d[date].values()) for date in d.keys()])
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel('[days]')
    plt.grid()
    plt.title(title)
    fig.autofmt_xdate()
    plt.draw()
    plt.show(block=False)
    return plt


def plot_details(title: str, d: dict):
    fig, ax = plt.subplots()
    for row in d[next(iter(d))].keys():
        ax.plot([date for date in d.keys()],
                [d[date][row] for date in d.keys()],
                label=row)
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel('[days]')
    plt.grid()
    plt.legend()
    plt.title(title)
    fig.autofmt_xdate()
    plt.draw()
    plt.show(block=False)
    return plt


def tabulate_details(d: dict):
    print(f'Date;{";".join(d[next(iter(d))].keys())};Summary')
    for date in d.keys():
        sval = [str(val) for val in d[date].values()]
        print(f'{date.strftime("%d.%m.%y")};{";".join(sval)};{sum(d[date].values())}')


def main():
    cfg = read_config()
    client = TrackerClient(cfg['token'], cfg['org'])
    assert client.myself is not None
    print('Crawling tracker...')
    # tabulate_details(spent(stories(client, g_project), by_component=True))
    # tabulate_details(x := estimate(epics(client, g_project), by_component=True))
    plt1 = plot_details('Estimates', estimate(epics(client, g_project), by_component=True))
    plt2 = plot_details('Spends', spent(epics(client, g_project), by_component=True))
    plt1.show()  # For IDE only


if __name__ == '__main__':
    main()
