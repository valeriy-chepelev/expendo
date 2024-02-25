from yandex_tracker_client import TrackerClient
import datetime as dt
from dateutil.rrule import rrule, DAILY, WEEKLY
import math
from functools import lru_cache
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import configparser
from alive_progress import alive_bar
from natsort import natsorted
import argparse

ByISSUE = 0
ByCOMPONENT = 1

"""
CLI request variants
expendo project [all] [COMPONENTS] [TODAY] [TABULATE]
expendo project velocities EPICS WEEKLY PLOT
expendo project spends STORIES [TODAY] [TABULATE]
expendo (MTPD-01,MTPD-02) estimates [COMPONENTS] DAILY [TABULATE]
"""


def read_config(filename):
    config = configparser.ConfigParser()
    config.read(filename)
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


def components(issues: list, w_bar=False):
    """ Return list of components assigned to issues and all of its descendants """
    comp = set()
    if w_bar:
        with alive_bar(len(issues), title='Components', theme='classic') as bar:
            for issue in issues:
                comp.update({comp.name for comp in issue.components})
                comp.update(set(components(_get_linked(issue))))
                bar()
    else:
        for issue in issues:
            comp.update({comp.name for comp in issue.components})
            comp.update(set(components(_get_linked(issue))))
    return sorted(list(comp))


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
            est = sum([issue_estimate(linked, date, component, own_comp
                       if len(own_comp) > 0 else default_comp)
                      for linked in _get_linked(issue)])
    return est


def spent(issues: list, dates: list, by_component=False):
    """ Return issues summary spent daily timeline as dictionary of
    {date: {issue_key: spent[days]}} for the listed issues.
    If by_component requested, collect spent for issues components and return
    timeline {date: {component: spent[days]}}.
    Issue in list should be yandex tracker reference."""
    all_components = components(issues, True)
    if by_component:
        with alive_bar(len(issues) * len(all_components),
                       title='Spends', theme='classic') as bar:
            return {date.date(): {component: sum([issue_spent(issue, date, component)
                                                  for issue in issues
                                                  if bar() not in ['nothing']])
                                  for component in all_components}
                    for date in dates}
    with alive_bar(len(issues),
                   title='Spends', theme='classic') as bar:
        return {date.date(): {issue.key: issue_spent(issue, date)
                              for issue in issues
                              if bar() not in ['nothing']}
                for date in dates}


def estimate(issues: list, dates: list, by_component=False):
    """ Return issues estimate daily timeline as dictionary of
    {date: {issue_key: estimate[days]}} for the listed issues.
    If by_component requested, collect estimates for issues components and return
    timeline {date: {component: estimate[days]}}.
    Issue in list should be yandex tracker reference."""
    all_components = components(issues, True)
    if by_component:
        with alive_bar(len(issues) * len(all_components),
                       title='Estimates', theme='classic') as bar:
            return {date.date(): {component: sum([issue_estimate(issue, date, component)
                                                  for issue in issues
                                                  if bar() not in ['nothing']])
                                  for component in all_components}
                    for date in dates}
    with alive_bar(len(issues),
                   title='Estimates', theme='classic') as bar:
        return {date.date(): {issue.key: issue_estimate(issue, date)
                              for issue in issues
                              if bar() not in ['nothing']}
                for date in dates}


def get_start_date(issues: list):
    """ Return start date (first estimation date) of issues """
    with alive_bar(len(issues), title='Start date', theme='classic') as bar:
        try:
            d = min([t[-1]['date'] for issue in issues
                     if (len(t := _get_issue_times(issue)) > 0) ^ (bar() in ['nothing'])])
        except ValueError:
            d = dt.datetime.now(dt.timezone.utc)
    return d


# Sprints info


@lru_cache(maxsize=None)  # Cashing access to YT
def issue_sprints(issue) -> list:
    """ Return list of issue sprints, including all the subtasks,
    according to the logs """
    spr = {sc[0].name} if (sc := issue.sprint) is not None and len(sc) > 0 else set()
    for log in issue.changelog:
        for field in log.fields:
            if field['field'].id == 'sprint':
                if (to := field['to']) is not None and len(to) > 0:
                    spr.add(to[0].name)
                if (fr := field['from']) is not None and len(fr) > 0:
                    spr.add(fr[0].name)
    for linked in _get_linked(issue):
        spr.update(issue_sprints(linked))
    return natsorted(list(spr))


def sprints(issues: list) -> list:
    """ Return list of sprints, where tasks was present, including all the subtasks,
    according to the logs """
    s = set()
    with alive_bar(len(issues), title='Sprints', theme='classic') as bar:
        for issue in issues:
            s.update(set(issue_sprints(issue)))
            bar()
    return natsorted(list(s))


# Data output routines


def tabulate_summary(d: dict):
    print('Date', 'Summary', sep='\t')
    for date in d.keys():
        print(date.strftime("%d.%m.%y"), sum(d[date].values()), sep='\t')


def plot_summary(title: str, d: dict):
    fig, ax = plt.subplots()
    ax.plot([date for date in d.keys()],
            [sum(d[date].values()) for date in d.keys()])
    formatter = DateFormatter("%d.%m.%y")
    ax.xaxis.set_major_formatter(formatter)
    plt.xlabel('Date')
    plt.ylabel('[hours]')
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
    plt.ylabel('[hours]')
    plt.grid()
    plt.legend()
    plt.title(title)
    fig.autofmt_xdate()
    plt.draw()


def tabulate_details(d: dict):
    print('Date', "\t".join(d[next(iter(d))].keys()), 'Summary', sep='\t')
    for date in d.keys():
        sval = "\t".join([str(val) for val in d[date].values()])
        print(date.strftime("%d.%m.%y"), sval, sum(d[date].values()), sep='\t')


def some_issues(client, keys: list):
    return [client.issues[e] for e in keys]


# g_project = "MT SystemeLogic(ACB)"  # Temporary, will be moved to argument parser
# g_project = "MT БМРЗ-60"  # Temporary, will be moved to argument parser
# g_project = "MT Дуга-О3"  # Temporary, will be moved to argument parser
# g_project = "MT SW SCADA"  # Temporary, will be moved to argument parser
g_project = "MT 150cry"  # Temporary, will be moved to argument parser


# g_project = "МТ M4Cry"  # Temporary, will be moved to argument parser
# g_project = "МТ IP1810"  # Temporary, will be moved to argument parser
# g_project = "Корпоративный профиль 61850"  # Temporary, will be moved to argument parser
# g_project = "MT FastView"  # Temporary, will be moved to argument parser


def define_parser():
    """ Return CLI arguments parser
    CLI request cases
    expendo project [all] [COMPONENTS] [TODAY] [DUMP]
    expendo project velocities EPICS WEEK PLOT
    expendo project spends STORIES [TODAY] [CSV]
    expendo (MTPD-01,MTPD-02) estimates [COMPONENTS] all [DUMP]
    """
    parser = argparse.ArgumentParser(description='Expendo v.1.0 - Yandex Tracker stat crawler by VCh.',
                                     epilog='Tracker connection settings and params in "expendo.ini".')
    parser.add_argument('scope',
                        help='project name or comma-separated issues keys (no space allowed)')
    parser.add_argument('parameter', choices=['spent', 'estimate', 'burn', 'all'],
                        help='measured value')
    parser.add_argument('grouping', choices=['epics', 'stories', 'components', 'queues'],
                        help='value grouping criteria')
    parser.add_argument('output', choices=['dump', 'plot', 'csv'],
                        help='output fromat')
    parser.add_argument('timespan', choices=['today', 'week', 'sprint', 'month', 'all'],
                        help='calculation time range')

    return parser


def get_scope(client, args):
    pass


def get_dates(client, args):
    pass


def main():
    cfg = read_config()
    client = TrackerClient(cfg['token'], cfg['org'])
    if client.myself is None:
        raise Exception('Unable to connect to Yandex Tracker.')
    args = define_parser().parse_args()  # get CLI arguments
    issues = get_scope(client, args)  # get issues objects
    dates = get_dates(client, args)  # get issues objects

    print(f'Crawling tracker "{g_project}"...')
    issues = epics(client, g_project)
    # issues = some_issues(client,['MTHW-894'])
    # print(sprints(issues))
    start_date = get_start_date(issues)
    final_date = dt.datetime.now(dt.timezone.utc)
    dates = list(rrule(DAILY, dtstart=start_date, until=final_date))
    # today = [final_date]
    est = estimate(issues,
                   dates,
                   by_component=True)
    spt = spent(issues,
                dates,
                by_component=True)
    # tabulate_details(est)
    # tabulate_details(spt)
    matplotlib.use('TkAgg')
    plot_details('Estimates', est)
    plot_details('Spends', spt)
    # plt.ion()  # Turn on interactive plotting - not working, requires events loop for open plots
    plt.show()
    input('Press any key...')  # for interactive mode


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Execution error:', e)
        input('Press any key to close...')