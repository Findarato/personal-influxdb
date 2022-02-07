#!/usr/bin/python3
# Copyright 2022 Sam Steele
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import requests, sys, logging
from datetime import date, datetime, time, timedelta
from publicsuffix2 import PublicSuffixList
from config import *

if not EXIST_ACCESS_TOKEN:
    logging.error("EXIST_ACCESS_TOKEN not set in config.py")
    sys.exit(1)

points = []
start_time = str(int(LOCAL_TIMEZONE.localize(datetime.combine(date.today(), time(0,0)) - timedelta(days=7)).astimezone(pytz.utc).timestamp()) * 1000) + 'ms'

def append_tags(tags):
    try:
        response = requests.post('https://exist.io/api/1/attributes/custom/append/',
            headers={'Authorization':f'Bearer {EXIST_ACCESS_TOKEN}'},
            json=tags)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    result = response.json()
    if len(result['failed']) > 0:
        logging.error("Request failed: %s", result['failed'])
        sys.exit(1)

    if len(result['success']) > 0:
        logging.info("Successfully sent %s tags", len(result['success']))

def acquire_attributes(attributes):
    try:
        response = requests.post('https://exist.io/api/1/attributes/acquire/',
            headers={'Authorization':f'Bearer {EXIST_ACCESS_TOKEN}'},
            json=attributes)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    result = response.json()
    if len(result['failed']) > 0:
        logging.error("Request failed: %s", result['failed'])
        sys.exit(1)

def post_attributes(values):
    try:
        response = requests.post('https://exist.io/api/1/attributes/update/',
            headers={'Authorization':f'Bearer {EXIST_ACCESS_TOKEN}'},
            json=values)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    result = response.json()
    if len(result['failed']) > 0:
        logging.error("Request failed: %s", result['failed'])
        sys.exit(1)

    if len(result['success']) > 0:
        logging.info("Successfully sent %s attributes" % len(result['success']))

client = connect(EXIST_DATABASE)

acquire_attributes([{"name":"gaming_min", "active":True}, {"name":"tv_min", "active":True}])

try:
    response = requests.get('https://exist.io/api/1/users/' + EXIST_USERNAME + '/insights/',
        headers={'Authorization':f'Bearer {EXIST_ACCESS_TOKEN}'})
    response.raise_for_status()
except requests.exceptions.HTTPError as err:
    logging.error("HTTP request failed: %s", err)
    sys.exit(1)

data = response.json()
logging.info("Got %s insights from exist.io", len(data['results']))

for insight in data['results']:
    if insight['target_date'] == None:
        date = datetime.fromisoformat(insight['created'].strip('Z')).strftime('%Y-%m-%d')
    else:
        date = insight['target_date']
    points.append({
        "measurement": "insight",
        "time": date + "T00:00:00",
        "tags": {
            "type": insight['type']['name'],
            "attribute": insight['type']['attribute']['label'],
            "group": insight['type']['attribute']['group']['label'],
        },
        "fields": {
            "html": insight['html'].replace("\n", "").replace("\r", ""),
            "text": insight['text']
        }
    })

try:
    response = requests.get('https://exist.io/api/1/users/' + EXIST_USERNAME + '/attributes/?limit=7&groups=custom,mood',
        headers={'Authorization':f'Bearer {EXIST_ACCESS_TOKEN}'})
    response.raise_for_status()
except requests.exceptions.HTTPError as err:
    logging.error("HTTP request failed: %s", err)
    sys.exit(1)

data = response.json()
logging.info("Got attributes from exist.io")

for result in data:
    for value in result['values']:
        if value['value'] and result['attribute'] != 'custom':
            if result['group']['name'] == 'custom':
                points.append({
                    "measurement": result['group']['name'],
                    "time": value['date'] + "T00:00:00",
                    "tags": {
                        "tag": result['label']
                    },
                    "fields": {
                        "value": value['value']
                    }
                })
            else:
                points.append({
                    "measurement": result['attribute'],
                    "time": value['date'] + "T00:00:00",
                    "fields": {
                        "value": value['value']
                    }
                })

write_points(points)

values = []
tags = []
if FITBIT_DATABASE and EXIST_USE_FITBIT:
    client.switch_database(FITBIT_DATABASE)
    durations = client.query(f'SELECT "duration" FROM "activity" WHERE (activityName = \'Meditating\' OR activityName = \'Meditation\')AND time >= {start_time}')
    for duration in list(durations.get_points()):
        if duration['duration'] > 0:
            date = datetime.fromisoformat(duration['time'].strip('Z') + "+00:00").astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d')
            tags.append({'date': date, 'value': 'meditation'})

    durations = client.query(f'SELECT "duration","activityName" FROM "activity" WHERE activityName != \'Meditating\' AND activityName != \'Meditation\' AND time >= {start_time}')
    for duration in list(durations.get_points()):
        if duration['duration'] > 0:
            date = datetime.fromisoformat(duration['time'].strip('Z') + "+00:00").astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d')
            tags.append({'date': date, 'value': 'exercise'})
            tags.append({'date': date, 'value': duration['activityName'].lower().replace(" ", "_")})

if TRAKT_DATABASE and EXIST_USE_TRAKT:
    totals = {}
    client.switch_database(TRAKT_DATABASE)
    durations = client.query(f'SELECT "duration" FROM "watch" WHERE time >= {start_time}')
    for duration in list(durations.get_points()):
        date = datetime.fromisoformat(duration['time'].strip('Z') + "+00:00").astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d')
        if date in totals:
            totals[date] = totals[date] + duration['duration']
        else:
            totals[date] = duration['duration']

    for date in totals:
        values.append({'date': date, 'name': 'tv_min', 'value': int(totals[date])})
        tags.append({'date': date, 'value': 'tv'})

if GAMING_DATABASE and EXIST_USE_GAMING:
    totals = {}
    client.switch_database(GAMING_DATABASE)
    durations = client.query(f'SELECT "value" FROM "time" WHERE "value" > 0 AND time >= {start_time}')
    for duration in list(durations.get_points()):
        date = datetime.fromisoformat(duration['time'].strip('Z') + "+00:00").astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d')
        if date in totals:
            totals[date] = totals[date] + duration['value']
        else:
            totals[date] = duration['value']

    for date in totals:
        values.append({'date': date, 'name': 'gaming_min', 'value': int(totals[date] / 60)})
        tags.append({'date': date, 'value': 'gaming'})
elif RESCUETIME_DATABASE and EXIST_USE_RESCUETIME:
    psl = PublicSuffixList()
    totals = {}
    client.switch_database(RESCUETIME_DATABASE)
    durations = client.query(f'SELECT "duration","activity" FROM "activity" WHERE category = \'Games\' AND activity != \'Steam\' AND activity != \'steamwebhelper\' AND activity != \'origin\' AND activity != \'mixedrealityportal\' AND activity != \'holoshellapp\' AND activity != \'vrmonitor\' AND activity != \'vrserver\' AND activity != \'oculusclient\' AND activity != \'vive\' AND activity != \'obs64\' AND time >= {start_time}')
    for duration in list(durations.get_points()):
        date = datetime.fromisoformat(duration['time'].strip('Z') + "+00:00").astimezone(LOCAL_TIMEZONE).strftime('%Y-%m-%d')
        if psl.get_public_suffix(duration['activity'], strict=True) is None:
            if date in totals:
                totals[date] = totals[date] + duration['duration']
            else:
                totals[date] = duration['duration']

    for date in totals:
        values.append({'date': date, 'name': 'gaming_min', 'duration': int(totals[date] / 60)})
        tags.append({'date': date, 'value': 'gaming'})

if len(tags) > 0:
    append_tags(tags)

if len(values) > 0:
    post_attributes(values)
