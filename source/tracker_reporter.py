
from tracker_data import _linked_issues, _issue_times, _issue_original, get_start_date
import datetime as dt
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

TODAY = dt.datetime.now(dt.timezone.utc).date()
ACTIVE_SPRINT_START = TODAY
FUTURE_SPRINT_START = TODAY
SPRINT_DAYS = [TODAY]
ALL_DAYS = [TODAY]
SPRINT_LEN = 14


def tasks(client, request, scan: bool = True) -> list:
    """ Search Tasks and Bugs using YT query.
    Includes all the sibling task within Epics and Stories given by query.
    :param client: TrackerClient object
    :param request: string with YT query language
    :param scan: scan and include all the sibling task within Epics and Stories given by request
    :return: list of YT issues objects"""
    issues = client.issues.find(query=request)
    tickets = {issue.key: issue for issue in issues if issue.type.key in ['task', 'bug']}
    if scan:
        ancestors = [issue for issue in issues if issue.type.key not in ['task', 'bug']]
        while ancestors:
            siblings = _linked_issues(ancestors.pop())
            tickets.update({issue.key: issue for issue in siblings if issue.type.key in ['task', 'bug']})
            ancestors.extend([issue for issue in siblings if issue.type.key not in ['task', 'bug']])
    return list(tickets.values())


def estimate(issues, date=TODAY):
    """
    Summ issues estimate up to the date (including).
    Assumed closed task always has zero estimation.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'estimation' and s['date'].date() <= date), 0)
                for issue in issues])


def original(issues, date=TODAY):
    """
    Summ original (first before WIP) issues estimate up to the date (including).
    Consider issue closing date. Ignores rejected issues.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :return: int hours
    """
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & (e.created <= date <= e.end)])


def spent(issues, date=TODAY, velo: bool = True):
    """
    Summ issues spent up to the date (including), total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param velo: period length in days, zero means all from the beginning
    :return: int hours
    """
    # TODO: change velo to period
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'spent' and s['date'].date() <= date), 0) -
                int(velo) * next((s['value'] for s in _issue_times(issue)
                                  if s['kind'] == 'spent' and s['date'].date() <=
                                  date - dt.timedelta(days=SPRINT_LEN)), 0)
                for issue in issues])


def burned(issues, date=TODAY, velo: bool = True):
    """
    Summ closed original (first before WIP) issues estimate up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param velo: period length in days, zero means all from the beginning
    :return: int hours
    """
    # TODO: change velo to period
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & e.finished &
                ((date - dt.timedelta(days=SPRINT_LEN) < e.end <= date) if velo else (e.end <= date))])


def count_created(issues, date=TODAY, period: int = 0):
    """
    Count issues created up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int issues count
    """
    pass


def count_wip(issues, date=TODAY, period: int = 0):
    """
    Count issues InProgress (once WIP, not closed or rejected) up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means all from the beginning
    :return: int issues count
    """
    pass


def count_success(issues, date=TODAY, period: int = 0):
    """
    Count resolved issues (not rejected) up to the date (including),
    total or for a period.
    :param issues: iterable of YT issues objects
    :param date: date part value of datetime
    :param period: period length in days, zero means total
    :return: int issues count
    """
    pass


def ttr_stat(issues):
    """
    Calculate issues time-to-resolve (from first WIP to last resolution).
    Ignores not resolved or rejected issues.
    :param issues: iterable of YT issues objects
    """
    pass


def ttj_stat(issues):
    """
    Calculate issues time-to-job (creation to first WIP).
    Ignores untouched issues.
    :param issues: iterable of YT issues objects
    """
    pass


def update_dates(config, issues):
    # reset globals to default today
    global ACTIVE_SPRINT_START
    global FUTURE_SPRINT_START
    global SPRINT_DAYS
    global ALL_DAYS
    global SPRINT_LEN
    ACTIVE_SPRINT_START = TODAY
    FUTURE_SPRINT_START = TODAY
    SPRINT_DAYS = [TODAY]
    ALL_DAYS = [TODAY]
    # convert values from config
    base_date = dt.datetime.strptime(config['sprint_base'], '%d.%m.%y').date()
    SPRINT_LEN = int(config['sprint_len'])
    # find sprint start by rounding today downward
    ACTIVE_SPRINT_START -= dt.timedelta(days=SPRINT_LEN - abs((ACTIVE_SPRINT_START - base_date).days) % SPRINT_LEN)
    # find sprint end by rounding today forward
    FUTURE_SPRINT_START += dt.timedelta(days=abs((FUTURE_SPRINT_START - base_date).days) % SPRINT_LEN)
    # get first estimation of issues
    start = get_start_date(issues, show_bar=False).date()
    # find first sprint by rounding start downward
    start -= dt.timedelta(days=SPRINT_LEN - abs((start - base_date).days) % SPRINT_LEN)
    # generate days and remove time
    SPRINT_DAYS = [r.date() for r in rrule(DAILY, interval=SPRINT_LEN, dtstart=start, until=FUTURE_SPRINT_START)]
    ALL_DAYS = [r.date() for r in rrule(DAILY, interval=1, dtstart=start, until=FUTURE_SPRINT_START)]


from expendo import read_config
from yandex_tracker_client import TrackerClient
from prettytable import PrettyTable
import pyperclip

cfg = read_config('expendo.ini')
client = TrackerClient(cfg['token'], cfg['org'])
ts = tasks(client, 'Project: "MT SystemeLogic(ACB)" AND Queue: MTHW')
print(f'{len(ts)} task(s) found.')
update_dates(cfg, ts)
table = PrettyTable()
table.field_names = ['Date', 'Estimate', 'Original', 'Spent', 'Burned']
velocity = False
for day in SPRINT_DAYS:
    table.add_row([day, estimate(ts, day),
                   original(ts, day),
                   spent(ts, day, velocity),
                   burned(ts, day, velocity)])
pyperclip.copy(table.get_csv_string())
table.align = 'r'
print(table)
