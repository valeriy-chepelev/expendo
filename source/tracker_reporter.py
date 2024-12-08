from tracker_data import _linked_issues, _issue_times, _issue_original, get_start_date
import datetime as dt
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

TODAY = dt.datetime.now(dt.timezone.utc).date()
ACTIVE_SPRINT_START = TODAY
FUTURE_SPRINT_START = TODAY
SPRINT_DAYS = [TODAY]
ALL_DAYS = [TODAY]
SPRINT_LEN = 14


def tasks(client, request) -> list:
    """ Return list of all Tasks and Bugs from the tracker request.
    Include all the sibling task within Epics and Stories given by request"""
    issues = client.issues.find(query=request)
    tickets = {issue.key: issue for issue in issues if issue.type.key in ['task', 'bug']}
    ancestors = [issue for issue in issues if issue.type.key not in ['task', 'bug']]
    while ancestors:
        siblings = _linked_issues(ancestors.pop())
        tickets.update({issue.key: issue for issue in siblings if issue.type.key in ['task', 'bug']})
        ancestors.extend([issue for issue in siblings if issue.type.key not in ['task', 'bug']])
    return list(tickets.values())


def estimate(issues, date=TODAY):
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'estimation' and s['date'].date() <= date), 0)
                for issue in issues])


def original(issues, date=TODAY):
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & (e.created <= date <= e.end)])


def spent(issues, date=TODAY, velo: bool = True):
    return sum([next((s['value'] for s in _issue_times(issue)
                      if s['kind'] == 'spent' and s['date'].date() <= date), 0) -
                int(velo) * next((s['value'] for s in _issue_times(issue)
                                  if s['kind'] == 'spent' and s['date'].date() <=
                                  date - dt.timedelta(days=SPRINT_LEN)), 0)
                for issue in issues])


def burned(issues, date=TODAY, velo: bool = True):
    return sum([e.original for issue in issues
                if (e := _issue_original(issue)).valuable & e.finished &
                ((date - dt.timedelta(days=SPRINT_LEN) < e.end <= date) if velo else (e.end <= date))])


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
    ACTIVE_SPRINT_START -= dt.timedelta(days=SPRINT_LEN-abs((ACTIVE_SPRINT_START-base_date).days) % SPRINT_LEN)
    # find sprint end by rounding today forward
    FUTURE_SPRINT_START += dt.timedelta(days=abs((FUTURE_SPRINT_START-base_date).days) % SPRINT_LEN)
    # get first estimation of issues
    start = get_start_date(issues, show_bar=False).date()
    # find first sprint by rounding start downward
    start -= dt.timedelta(days=SPRINT_LEN-abs((start-base_date).days) % SPRINT_LEN)
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
