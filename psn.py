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

import requests
import sys
import json
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
#from config_dev import *
from config import *


if not EXOPHASE_NAME:
    logging.error("EXOPHASE_NAME not set in config.py")
    sys.exit(1)

points = []


def scrape_exophase_id():
    try:
        response = requests.get(
            f"https://www.exophase.com/user/{EXOPHASE_NAME}")
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)
    soup = BeautifulSoup(response.text, 'html.parser')
    return [soup.find("a", attrs={'data-playerid': True})['data-playerid'], soup.find("div", attrs={'data-userid': True})['data-userid']]


def scrape_latest_games(platform):
    games = []
    try:
        response = requests.get(
            f"https://www.exophase.com/{platform}/user/{PSN_NAME}")
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)
    soup = BeautifulSoup(response.text, 'html.parser')
    for game in soup.find_all("li", attrs={'data-gameid': True}):
        try:
            playtime = int(float(game.select_one(
                "span.hours").get_text()[:-1]) * 60)
            img = game.select_one("div.image > img")['src']
            img = urljoin(img, urlparse(img).path).replace(
                "/games/m/", "/games/l/")
            games.append({'gameid': game['data-gameid'],
                          'time': datetime.fromtimestamp(float(game['data-lastplayed'])),
                          'title': game.select_one("h3 > a").string,
                          'url': game.select_one("h3 > a")['href'],
                          'image': img,
                          'playtime': playtime,
                          })
        except Exception:  # Games with out total played time
            pass

    return games


def scrape_achievements(url, gameid):
    achievements = []
    try:
        response = requests.get(
            f"https://api.exophase.com/public/player/{urlparse(url).fragment}/game/{gameid}/earned")

        response.raise_for_status()

        api_data = response.json()

    except requests.exceptions.HTTPError as err:
        logging.error("HTTP request failed: %s", err)
        sys.exit(1)

    if api_data['success'] == True:
        achievement_data = {}

        for achievement in api_data['list']:
            api_desc_response = requests.get(achievement["endpoint"])
            soup = BeautifulSoup(api_desc_response.text, 'html.parser')
            award = soup.find("div", {"class": "col award-details snippet"}).p

            achievement_data = {'id': achievement['awardid'],
                                'name': achievement["slug"].replace("-", " ").title(),
                                'image': achievement["icons"]["o"],
                                'time': datetime.fromtimestamp(achievement['timestamp']),
                                'description': award.text
                                }
            achievements.append(achievement_data)

    return achievements


client = connect(PSN_DATABASE)

PLAYERID, USERID = scrape_exophase_id()
totals = client.query(
    f'SELECT last("total") AS "total" FROM "time" WHERE "platform" = \'PSN\' AND "total" > 0 AND "player_id" = \'{PLAYERID}\' GROUP BY "application_id" ORDER BY "time" DESC')

for game in scrape_latest_games('psn'):

    play_time = game['playtime']
    total = list(totals.get_points(
        tags={'application_id': str(game['gameid'])}))


    # if len(total) == 1 and total[0]['total'] > 0:
    #     play_time = game['playtime'] - total[0]['total']

    # if total[0]['total'] > 0:
    #     play_time = game['playtime'] - total[0]['total']

    # print(game['playtime'])
    # sys.exit()

    if game['playtime'] > 1:
        points.append({
            "measurement": "time",
            "time": game['time'].isoformat(),
            "tags": {
                "player_id": PLAYERID,
                "application_id": game['gameid'],
                "platform": "PSN",
                "player_name": PSN_NAME,
                "title": game['title'],
            },
            "fields": {
                "value": int(play_time),
                "total": game['playtime'],
                "image": game['image'],
                "url": game['url']
            }
        })

    for achievement in scrape_achievements(game['url'], game['gameid']):
        points.append({
            "measurement": "achievement",
            "time": achievement['time'].isoformat(),
            "tags": {
                "player_id": PLAYERID,
                "application_id": game['gameid'],
                "apiname": achievement['id'],
                "platform": "PSN",
                "player_name": PSN_NAME,
                "title": game['title'],
            },
            "fields": {
                "name": achievement['name'],
                "description": achievement['description'],
                "icon": achievement['image'],
                "icon_gray": achievement['image'],
            }
        })

# json_formatted_str = json.dumps(points, indent=2)

# print(json_formatted_str)

# print(points)
write_points(points)
