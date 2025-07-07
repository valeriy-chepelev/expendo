# Abstract

Package contain functions to retrieve statistical data from Yandex Tracker issues database:
* for a fixed date
* on a daily basis
* on a sprint basis (period) according to a given sprint length and base date

Functions retrieve data directly from Yandex Tracker using API. Requires org id and API access token with R/O rights.
Data is collected from the history of each task.

Data functions process a set of selected issues and return summary values.
Issues can be selected manually or by special designed selecting functions.
You can select and process all the tasks and bugs within the epic, for example.
Or specially tagged tasks within all the project.

## Caching

Functions caches some Tracker data to folder 'Cache' to improve performance.
Cache updated daily.
Clear or delete 'Cache' folder to get the freshest data from Tracker. 

## Selection functions

* Select via Yandex Tracker query
* Scan for a subtasks with a posterior Yandex Tracker query

## Data functions
* Count of created tasks
* Count of tasks in progress
* Count of resolved tasks
* Time to start (TTS, from creation to take-on)
* Time to resolve (TTR, from take-on to resolve)
* Estimation (burn-down chart)
* Spent
* Original estimation
* Burned (resolved) original estimation
* Prediction rate for resolved tasks (spent to original estimate ratio)
* Assignee load (spent to TTR ratio, pauses rejected)

Some terms:
* Estimation is a remaining cost of task, corrected according to the task progress.
* Spent is cost of perfomed job.
* Original estimation is predicted estimation of task cost at the moment task first started.
* Burned original estimate is a value of original estimate if task complete and resolved, otherwise 0.

## Performace

# Usage

    # Connect to Yandex Tracker
    from yandex_tracker_client import TrackerClient
    client = TrackerClient('my_token', 'my_org_id')

    # Query issues from project, tagged with 'firmware'
    issues = client.issues.find(query='Project: "My Project" AND Tags: firmware')

    # Define options, create instance for a selected issues
    import expendo
    stat = expendo.Expendo(options, issues) 

    # Show totals
    print(f'{stat.created(NOW)} issue(s) created.')