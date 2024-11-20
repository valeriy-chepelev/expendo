from tracker_data import _linked_issues, _issue_times, _issue_original
import datetime as dt
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY

EST_CLASSIC = 0
EST_ORIGINAL = 1

TODAY = dt.datetime.now(dt.timezone.utc)
ACTIVE_SPRINT_START = TODAY
FUTURE_SPRINT_START = TODAY


def tasks(client, request) -> list:
    """ Return list of all Tasks and Bugs from the tracker request.
    Include all the sibling task within Epics and Stories given by request"""
    issues = client.issues.find(query=request)
    tickets = set(issue for issue in issues if issue.type.key in ['task', 'bug'])
    ancestors = [issue for issue in issues if issue.type.key not in ['task', 'bug']]
    while ancestors:
        siblings = _linked_issues(ancestors.pop())
        tickets.update([issue for issue in siblings if issue.type.key in ['task', 'bug']])
        ancestors.extend([issue for issue in siblings if issue.type.key not in ['task', 'bug']])
    return list(tickets)


def estimate(issues, date, mode=EST_CLASSIC):
    if mode == EST_CLASSIC:
        return sum([next((s['value'] for s in _issue_times(issue) if s['kind'] == 'estimation'), 0)
                    for issue in issues])
    return sum([_issue_original(issue).original for issue in issues])
