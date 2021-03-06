################################################################################
## takes a DB of movies in a queue and the html block of movies from a Netflix
## queue, collects streaming information and metadata about the movies and
## provides an interface for a user to pick a movie to watch.
##
## to use you need a The Movie Database API key and to place an html block from
## your Netflix DVD queue in a file called queue_body.html. the block of interest
## can be copied in Chrome by choosing "Inspect Element" over your DVD queue
## (https://dvd.netflix.com/Queue), selecting the div where id="sortable" and
## aria-label="Active queue list" and right-clicking to select copy outerHTML.
## then paste that into queue_body. if you would also like to include in movies
## from the Saved section of your Netflix queue (movies that aren't released yet
## on Netflix DVD but may be available on streaming services) then follow the
## same procedure above, but for "savedListQueue" and copy that outerHTML into
## saved_queue.html. Use the flag --saved to process movies from the Saved
## section of your DVD queue. The same procedure applies to movies in your "My
## List" (streaming queue) that you would like to add, instead you will select
## the div with class "rowList" using Chrome's "Inspect Element" feature on
## https://www.netflix.com/browse/my-list and right-clicking to select copy the
## outerHTML and pasting that into my_list.html. Be sure to use the flag
## --mylist to process these movies.
##
## after the first pass through your queue a DB of the entries and info will be
## saved to movies_db.json. from that point forward you can choose to update the
## streaming information in your DB by passing "update" as a command line arg.
## and if you add or remove movies from your queue you will want to re-copy the
## html block into queue_body.html as instructed above.
################################################################################

import csv
import sys
import os
import re
import time
from unidecode import unidecode
from bs4 import BeautifulSoup
import pandas as pd
import tmdbsimple as tmdb
import requests
from functools import partial
from justwatch import JustWatch
import numpy as np
import json
import shutil
import argparse
import pdb

def search(movie):
    try:
        r = requests.get('http://www.canistream.it/services/search',
            params={'movieName': movie},
            headers={
                'User-Agent':
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36'
                    '(KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36'})
        if hasattr(r, 'json'):
            try:
                req = r.json()
                return(req)
            except:
                return None
        else:
            return None
    except:
        print(sys.exc_info()[0])
        return None

def movie(movie_id, media_type):
    try:
        r = requests.get('http://www.canistream.it/services/query',
            params={'movieId': movie_id,
                    'attributes': '1',
                    'mediaType': media_type},
            headers={
                'User-Agent':
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36'
                    '(KHTML, like Gecko) Chrome/42.0.2311.135 Safari/537.36'})
        if hasattr(r, 'json'):
            try:
                req = r.json()
                return(req)
            except:
                return None
        else:
            return None
    except:
        print(sys.exc_info()[0])
        return None


streaming = partial(movie, media_type='streaming')

## deprecated
def getStreams(cisi_id):
    streams = streaming(cisi_id)
    ss = []
    if streams is not None and len(streams) > 0:
        for k, v in streams.items():
            stream = str(v['friendlyName'])
            if stream != 'Youtube Free': ## Youtube Free isn't free...
                ss.append(stream)
    return ss

## deprecated
def parseCISI(title, tmdb_title = None):
    movs = search(title)
    mov = None
    mov_id = None
    imdb_id = None
    year = InstantNone
    ss = []
    sel = 'n'
    if movs is not None and len(movs) > 0:
        for m in movs:
            cisi_title = unidecode(m['title']).replace(',', '')
            if cisi_title.lower() == title.lower():
                sel = 'y'
                break
            elif title.lower() in cisi_title.lower() or cisi_title.lower() in title.lower():
                sel = input(
                    "Matching '{}' with canistream.it '{}' ({})... OK? [y or n] ".format(
                        title
                        , cisi_title
                        , m['_id']
                    )
                ).lower()
                if sel == 'y':
                    break
            print("Trying again...")
    elif tmdb_title is not None:
        movs = search(tmdb_title)
        sel = 'n'
        if movs is not None and len(movs) > 0:
            for m in movs:
                cisi_title = unidecode(m['title'].decode('utf-8'))
                if cisi_title.lower() == tmdb_title.lower():
                    sel = 'y'
                    break
                elif tmdb_title.lower() in cisi_title.lower() or cisi_title.lower() in tmdb_title.lower():
                    sel = input(
                        "Matching TMDB '{}' with canistream.it '{}' ({})... OK? [y or n] ".format(
                            tmdb_title
                            , cisi_title
                            , m['_id']
                        )
                    ).lower()
                    if sel == 'y':
                        break
                    else:
                        print("Trying again...")
    if sel == 'y':
        mov = m
        mov_id = str(m['_id'])
        year = int(m['year'])
        if 'imdb' in m['links'].keys():
            imdb_id = str(m['links']['imdb'].split("/")[-2])
    else:
        print("Unable to find match in canistream.it for '{}'".format(title))
    if mov is not None:
        ss = getStreams(mov_id)
        print("* MATCHED canistream.it")
    elif tmdb_title is not None:
        print("Streaming availability won't be available.")
    return mov_id, year, ss, imdb_id


def parseTMDB(r):
    tmdb_id = float(r['id'])
    mov = tmdb.Movies(tmdb_id).info()
    year = float(mov['release_date'].split("-")[0]) if len(mov['release_date'].split("-")[0]) > 0 else np.nan
    genres = mov['genres'] if mov['genres'] is not None else []
    imdb_id = str(mov['imdb_id']) if mov['imdb_id'] is not None else None
    overview = unidecode(mov['overview']) if mov['overview'] is not None else None
    tagline = unidecode(mov['tagline']) if mov['tagline'] is not None else None
    lang = mov['original_language'] if mov['original_language'] is not None else None
    runtime = float(mov['runtime']) if mov['runtime'] is not None else np.nan
    gs = [str(g['name']) for g in genres]
    if lang != 'en' and 'Foreign' not in gs:
        gs.append(str('Foreign'))
    return tmdb_id, year, overview, tagline, runtime, gs, imdb_id

def findTMDB(title, imdb_id = None):
    page = 1
    sel = 'n'
    tmdb_id = None
    year = None
    overview = None
    runtime = None
    tagline = None
    gs = []
    tmdb_title = None
    if imdb_id is not None:
        res = tmdb.Find(imdb_id).info(external_source = 'imdb_id')['movie_results']
        if len(res) > 0:
            tmdb_id, year, overview, tagline, runtime, gs, imdb_id = parseTMDB(res[0])
            tmdb_title = None
            sel = 'y'
    while sel != 'y' and page <= 5:
        res = tmdb.Search().movie(query = title, page = page)
        page += 1
        if len(res['results']) == 0: break
        for r in res['results']:
            tmdb_title = unidecode(r['title']).replace(',', '')
            if tmdb_title.lower() == title.lower():
                sel = 'y'
            elif title.lower() in tmdb_title.lower() or tmdb_title.lower() in title.lower():
                sel = input(
                    "Matching '{}' with TMDB '{}' ({})... OK? [y or n] ".format(title, tmdb_title, r['id'])
                ).lower()
            if sel == 'y':
                tmdb_id, year, overview, tagline, runtime, gs, imdb_id = parseTMDB(r)
                break
            else:
                print("Trying again...")

    if sel != 'y':
        print("Unable to find match in TMDB for '{}'".format(title))
        print("Genres won't be available.")
        user_genres = input("Enter genres separated by commas if you want to include manually: ")
        gs = [x.strip() for x in user_genres.split(',')]
        tmdb_title = None
    else:
        print("* MATCHED TMDB")
    return tmdb_id, year, overview, tagline, runtime, gs, imdb_id, tmdb_title


def parseScore(scores, prov = 'tomato:meter'):
    if len(scores):
        rt_scores = [x for x in scores if prov in x['provider_type']]
        if len(rt_scores):
            return(float(rt_scores[0]['value']))
        else:
            return np.nan
    else:
        return np.nan

def parseGenres(gs):
    if not not gs:
        pdb.set_trace()
    else:
        return []

def getProviders():
    with open("config/providers.json", "r") as f:
        providers = json.load(f)
    jw = JustWatch(country = "US")
    provider_details = jw.get_providers()
    for provider in provider_details:
        providers[str(provider['id'])] = provider
    with open("config/providers.json", "w") as f:
        json.dump(providers, f)
    return providers

providers = getProviders()

provider_map = {'Netflix Instant' : 'Netflix',
                'Amazon Prime' : 'Amazon',
                'Amazon Instant Video' : 'Amazon',
                'Amazon Prime Instant Video' : 'Amazon',
                'HBO Now' : 'HBO',
                'HBO Go' : 'HBO'}

my_providers = ['History', 'Lifetime', 'A&E', 'The CW', 'Max Go', 'Starz',
                'Netflix', 'ABC', 'FXNow', 'Tubi TV', 'Yahoo View', 'NBC',
                'CBS', 'Amazon', 'Crackle', 'AMC', 'HBO', 'Showtime', 'Epix']

def parseStreams(streams):
    ss = []
    if not not streams:
        for s in streams:
            if any(x in s['monetization_type'] for x in ['flatrate', 'flat_rate', 'free']):
                prov = providers[str(s['provider_id'])]
                name = prov['clear_name']
                if name in provider_map:
                    short_name = provider_map[name]
                else:
                    short_name = name
                if short_name in my_providers:
                    ss.append(short_name)
    return ss

def parseJustWatch(mov):
    jw_id = float(mov['id'])
    year = float(mov['original_release_year']) if 'original_release_year' in mov.keys() else np.nan
    desc = unidecode(mov['short_description']) if 'short_description' in mov.keys() else None
    runtime = float(mov['runtime']) if 'runtime' in mov.keys() else np.nan
    rt_score = parseScore(mov['scoring']) if 'scoring' in mov.keys() else np.nan
    gs = parseGenres(mov['genre_ids']) if 'genre_ids' in mov.keys() else []
    streams = parseStreams(mov['offers']) if 'offers' in mov.keys() else []
    lang = mov['original_language'] if 'original_language' in mov.keys() else None

    if lang is not None and lang != 'en':
        if 'Foreign' not in gs:
            gs.append(str('Foreign'))
    return jw_id, year, desc, runtime, rt_score, gs, streams

def findJustWatch(title):
    sel = 'n'
    jw_id = np.nan
    year = np.nan
    desc = None
    runtime = np.nan
    rt_score = np.nan
    gs = []
    streams = []
    jw_title = None
    jw = JustWatch(country = "US")
    res = jw.search_for_item(query = title)
    while sel != 'y' and res['total_results'] > 0:
        for r in res['items']:
            jw_title = unidecode(r['title']).replace(',', '')
            if jw_title.lower() == title.lower():
                sel = 'y'
            elif title.lower() in jw_title.lower() or jw_title.lower() in title.lower():
                sel = input(
                    "Matching '{}' with JustWatch '{}' ({})... OK? [y or n] ".format(title, jw_title, r['id'])
                ).lower()
            if sel == 'y':
                jw_id, year, desc, runtime, rt_score, gs, streams = parseJustWatch(r)
                break
            else:
                print("Trying again...")
        break
    if sel != 'y':
        print("Unable to find match in JustWatch for '{}'".format(title))
        print("Streams won't be shown.")
        jw_id = input("Enter the JustWatch ID for the movie if it exists: ")
        if jw_id == '':
            jw_id = np.nan
        else:
            jw_id = float(jw_id)
        user_streams = input("Enter streams separated by commas if you want to include manually (ie. HBO, Amazon, Netflix, FXNow): ")
        if user_streams != '':
            streams = [x.strip() for x in user_streams.split(',')]
        print("Rotten Tomatoes score won't be shown.")
        user_score = input("Enter Rotten Tomatoes score if you want to include manually: ")
        if user_score == '':
            rt_score = np.nan
        else:
            rt_score = float(user_score)
        jw_title = None
    else:
        print("* MATCHED JustWatch")
    return jw_id, year, desc, runtime, rt_score, gs, streams, jw_title

def getJustWatch(title, jw_id, rt_score, streams, gs):
    sel = 'n'
    jw = JustWatch(country = "US")
    ## JustWatch breaks if you bombard it too much, so use a VPN
    while True:
        try:
            res = jw.search_for_item(query = title)
        except:
            print("JustWatch not reached. Try again...")
            print("** Rate Limit was likely exceeded. Please use VPN. **")
        else:
            break
    while sel != 'y' and res['total_results'] > 0:
        for r in res['items']:
            if r['id'] == int(jw_id):
                sel = 'y'
                jw_id, year, desc, runtime, rt_score, gs, streams = parseJustWatch(r)
                break
            else:
                print("Trying again...")
        break
    if sel != 'y':
        print("Results didn't contain match for '{}' using ID ({}).".format(title, jw_id))
        new_jw_id = input("Enter the JustWatch ID for the movie if it exists (or [return] to keep current value): ")
        if new_jw_id == '':
            jw_id = jw_id
        else:
            jw_id = float(new_jw_id)
        print("Current streams: {}".format(streams))
        user_streams = input("Enter streams separated by commas if you want to include manually (or [return] to keep current): ")
        if user_streams != '':
            for s in [x.strip() for x in user_streams.split(',')]:
                if s not in streams:
                    streams.append(s)
        print("Current Rotten Tomatoes score: {}".format(rt_score))
        user_score = input("Enter Rotten Tomatoes score if you want to include manually (or [return] to keep current): ")
        if user_score == '':
            rt_score = rt_score
        else:
            rt_score = float(user_score)
    else:
        print("* MATCHED JustWatch")
    return jw_id, rt_score, streams, gs


def process(soup, movies_db, mode = 'queue', queue = 'Queue', *html):
    if mode not in ['queue', 'saved', 'list', 'gallery']:
        sys.exit("mode parameter must be one of 'queue', 'saved', list', or 'gallery'")

    movies = []
    for mov in soup.find_all(*html):
        ## skip if TV show
        if mode == 'list' and 'Season' in mov.findNext('span', {'class', 'duration'}).text:
            continue
        if mode == 'saved' and mov.get('class') == ['heading']:
            continue

        m = [m for m in mov.strings]
        m = [x.replace(',', '') for x in m]

        if mode == 'queue':
            title = unidecode(m[4]).strip()
            print(title)
        elif mode == 'saved':
            title = unidecode(m[2]).strip()
            print(title)
        else:
            title = unidecode(m[0]).strip()
            print(title)

        if 'future release' in m or 'Future release' in m:
            print("Skipping '{}' because it's a Future release.".format(title))
            continue
        if 'Play' in m:
            netflix_instant = True
        elif mode in ['list', 'gallery']:
            netflix_instant = True
        else:
            netflix_instant = False

        ## section if you want to use the new netflix percentage match-score
        nextdiv = mov.findNext('div')
        if nextdiv is not None:
            spans = mov.findNext('div').find_all('span', {'class', 'match-score'})
        else:
            spans = []
        if len(spans) < 1:
            pct_rating = np.nan
        else:
            pct_rating = spans[0].text.split("% ")[0]
            if 'New' in pct_rating:
                pct_rating = np.nan
            else:
                pct_rating = round(float(pct_rating) / 20.0, 1)

        ## old code from before Netflix changed streaming from star ratings to
        ## match percentages
        # spans = mov.findNext('div').find_all('span', {'class', 'star'})
        # sbplaceholder = [i for i, item in enumerate(spans) if re.search(
        #     'sb-placeholder', item['class'][1]
        # )]
        # if len(sbplaceholder):
        #     base = sbplaceholder[0] - 1
        # else:
        #     base = 5.0
        # percent = [s for s in spans if re.search('percent', s['class'][2])]
        # if len(percent):
        # decimal = float(filter(
        #     str.isdigit,
        #     str([s for s in spans if re.search(
        #         'percent', s['class'][2]
        #     )][0]['class'][2])
        # )) / 100
        # else:
        #     decimal = 0
        # rating = base + decimal

        if mode == 'queue' or mode == 'saved':
            rating = float(
                mov.find('span', {'class' : 'starbar'})['data-rating'].encode('utf-8')
            )
            netflix_id = int(
                mov.find('span', {'class' : 'starbar'})['data-movie'].encode('utf-8')
            )
        elif mode == 'list':
            rating = None
            netflix_id = int(mov['videoid'])
        elif mode == 'gallery':
            rating = None
            netflix_id = int(mov.findPrevious('a')['href'].split('/')[-1].split('?')[0])

        ## update ratings, queues, Netflix streams if already in the database, then skip to next movie
        if not movies_db.empty:
            cond1 = any(float(netflix_id) == movies_db.netflix_id.values)
            cond2 = any(int(netflix_id) == movies_db.netflix_id.values)
            if cond1 or cond2:
                idx = movies_db[movies_db.netflix_id == netflix_id].index[0]
                ## update which Queue the movie is in
                queues = movies_db.loc[idx, 'queue']
                queues.append(queue)
                movies_db.set_value(idx, 'queue', queues)
                ## if movie has already been rated, remove from DB, assume it's been watched
                if mode in ['queue', 'saved'] and mov.find('span', {'class' : 'rated'}) is not None:
                    movies_db = movies_db[movies_db.netflix_id != int(netflix_id)]
                    print("Skipping '{}' because it has already been watched and rated.".format(title))
                else:
                    if rating is None:
                        rating = tryFloat(movies_db.loc[idx, 'rating'], get = True)
                    if rating == "":
                        rating = np.nan
                    if np.isnan(rating):
                        movies_db.set_value(idx, 'rating', pct_rating)
                    else:
                        movies_db.loc[idx, 'rating'] = rating
                    movies_db.loc[idx, 'netflix_instant'] = netflix_instant
                    prev_streams = movies_db.loc[idx, 'streams']
                    if netflix_instant and 'Netflix' not in prev_streams:
                        prev_streams.append(str('Netflix'))
                    if prev_streams is not None:
                        prev_streams = list(set(prev_streams))
                    movies_db = movies_db.set_value(idx, 'streams', prev_streams)
                continue

        ## movie is not in the database but has already been watched and rated, skip
        if mov.find('span', {'class' : 'rated'}) is not None:
            print("Skipping '{}' because it has already been watched and rated.".format(title))
            continue

        user_in = input("Add '{}' to the database? [y or n] ".format(title))
        if user_in != 'y':
            print("Skipping...")
            continue

        if rating is None:
            rate = input("What is your predicted Netflix rating for '{}'? ".format(title))
            rating = tryFloat(rate, get = True)

        cisi_id, jw_year, tmdb_year, jw_runtime, tmdb_runtime, tmdb_id, jw_id, rt_score = (np.nan,) * 8
        imdb_id, overview, tagline, tmdb_title, jw_title = (None,) * 5
        ss, gs = ([],) * 2

        ## justwatch block
        jw_id, jw_year, desc, jw_runtime, rt_score, genres, streams, jw_title = findJustWatch(title)

        ## tmdb block
        tmdb_id, tmdb_year, overview, tagline, tmdb_runtime, gs, imdb_id, tmdb_title = findTMDB(title, imdb_id)

        ## double-check adding netflix instant
        if netflix_instant and 'Netflix' not in streams:
            ss.append(str('Netflix'))

        ## get year, prefer JustWatch
        year = jw_year if not np.isnan(jw_year) else tmdb_year
        if not isinstance(year, float) or np.isnan(year):
            if mov.find('p', {'class' : 'metadata'}).find('span') is not None:
                year = float(mov.find('p', {'class' : 'metadata'}).find('span').text)

        ## get runtime, prefer TMDB
        if isinstance(tmdb_runtime, float) and not np.isnan(tmdb_runtime):
            runtime = tmdb_runtime
        else:
            runtime = jw_runtime

        ## get overview and tagline
        if tagline is None:
            tagline = desc
        if overview is None:
            overview = desc

        ## get streams
        if any(streams):
            ss = streams
        ## just to be sure
        if ss is None or not any(ss):
            ss = []

        ## combine genres
        if any(genres):
            for g in genres:
                if g not in gs:
                    gs.append(g)
        if 'Comedy' in gs:
            user_in = input("Is {} in the 'Stand-Up' genre? [y or n] ".format(title))
            if user_in == 'y':
                gs.append('Stand-Up')
        ## just to be sure
        if gs is None or not any(gs):
            gs = []

        movies.append({
            'netflix_id' : netflix_id
            , 'tmdb_id' : tmdb_id
            , 'canistreamit_id' : cisi_id
            , 'imdb_id' : imdb_id
            , 'title' : title
            , 'rating' : rating
            , 'genres' : gs
            , 'netflix_instant' : netflix_instant
            , 'streams' : ss
            , 'year' : year
            , 'runtime' : runtime
            , 'overview' : overview
            , 'tagline' : tagline
            , 'jw_id' : jw_id
            , 'rt_score' : rt_score
            , 'queue' : [queue]
        })
        with open('new_movies.json', 'w') as outfile:
            json.dump(movies, outfile)

    return movies, movies_db

def tryFloat(x, get = False):
    try:
        float(x)
    except:
        if get:
            return str(x)
        else:
            return False
    if get:
        return float(x)
    else:
        return True

## load api key for TMDB
with open("config/config.csv") as f:
    reader = csv.reader(f)
    config = {}
    for row in reader:
        config[row[0]] = row[1]

tmdb.API_KEY = config['TMDB_API_KEY']

parser = argparse.ArgumentParser()
parser.add_argument(
    "--update",
    help = "update streaming status and rotten tomatoes score of movies already in database",
    action = "store_true"
)
parser.add_argument("--saved", help = "also process movies in saved queue",
                    action = "store_true")
parser.add_argument("--mylist", help = "also process movies from my list (streaming queue)",
                    action = "store_true")
parser.add_argument("--gallery", help = "also process movies from gallery (streaming queue)",
                    action = "store_true")
args = parser.parse_args()

## whether canistream.it should be checked for existing DB entries to update streams
if args.update:
    update = True
else:
    update = False
    print("To update the streaming status and rotten tomatoes scores of existing movies, enter '--update' as a command line argument.\n")

## backup database file
shutil.copyfile('databases/movies_db.json', 'databases/backup/movies_db.json')

## load database
try:
    with open("databases/movies_db.json", "r") as f:
        movies_in = json.load(f)
        movies_db = pd.DataFrame(movies_in)
except:
    movies_db = pd.DataFrame({
            'netflix_id' : []
            , 'tmdb_id' : []
            , 'canistreamit_id' : []
            , 'imdb_id' : []
            , 'title' : []
            , 'rating' : []
            , 'genres' : []
            , 'netflix_instant' : []
            , 'streams' : []
            , 'year' : []
            , 'runtime' : []
            , 'overview' : []
            , 'tagline' : []
            , 'jw_id' : []
            , 'rt_score' : []
            , 'queue' : []
    })

## load netflix queue
with open("input/queue_body.html", "r") as f:
    soup = BeautifulSoup(f, 'html.parser')

genres = tmdb.Genres().movie_list()['genres']
alt_genres = [{'id' : 10769, 'name' : 'Foreign'}]

print("\nProcessing Active queue...\n")
## reset queue field
movies_db.queue = pd.Series(
    [list([a]) if not isinstance(a, list) else a for a in movies_db.queue.values]
)
movies_db.queue = [[q for q in qq if q != 'Queue'] for qq in movies_db.queue]

## process queue
movies, movies_db = process(
    soup,
    movies_db,
    'queue',
    'Queue',
    'li', {'class' : 'queue-item'}
)

if args.saved:
    with open("input/saved_queue.html", "r") as f:
        soup = BeautifulSoup(f, 'html.parser')
    ## reset queue field
    movies_db.queue = [[q for q in qq if q != 'Saved'] for qq in movies_db.queue]
    print("\nProcessing Saved queue...\n")
    saved_movies, movies_db = process(soup, movies_db, 'saved', 'Saved', 'li')
else:
    saved_movies = None
    print("\nSaved queue will not be processed. To process saved queue as well use command line arg --saved.")
if args.mylist:
    with open("input/my_list.html", "r") as f:
        soup = BeautifulSoup(f, 'html.parser', from_encoding = 'utf-8')
    ## reset queue field
    movies_db.queue = [[q for q in qq if q != 'Streaming'] for qq in movies_db.queue]
    print("\nProcessing My List (streaming queue)...\n")
    mylist_movies, movies_db = process(
        soup,
        movies_db,
        'list',
        'Streaming',
        'div', 'rowListItem'
    )
    ## clean up Netflix streaming info
    streams = []
    for ss, qq in zip(movies_db.streams, movies_db.queue):
        if 'Netflix' in ss and 'Streaming' not in qq:
            streams.append(list(set([s for s in ss if s != 'Netflix'])))
        else:
            streams.append(list(set(ss)))
    movies_db.streams = pd.Series(streams)
else:
    mylist_movies = None
    print("\nMy List (streaming queue as a list) will not be processed. To process Streaming Queue as well use command line arg --mylist.")
if args.gallery:
    with open("input/my_gallery.html", "r") as f:
        soup = BeautifulSoup(f, 'html.parser', from_encoding = 'utf-8')
    ## reset queue field
    movies_db.queue = [[q for q in qq if q != 'Streaming'] for qq in movies_db.queue]
    print("\nProcessing Gallery (streaming queue)...\n")
    gallery_movies, movies_db = process(
        soup,
        movies_db,
        'gallery',
        'Streaming',
        'video-preload-title-label'
    )
    ## clean up Netflix streaming info
    streams = []
    for ss, qq in zip(movies_db.streams, movies_db.queue):
        if 'Netflix' in ss and 'Streaming' not in qq:
            streams.append([s for s in ss if s != 'Netflix'])
        else:
            streams.append(ss)
    movies_db.streams = pd.Series(streams)
else:
    gallery_movies = None
    print("\nGallery (streaming queue as a gallery) will not be processed. To process Streaming Queue as well use command line arg --gallery.")

if update:
    print("\nUpdating database with streaming availability...\n")
    for idx, row in movies_db.iterrows():
        title = movies_db.loc[idx, 'title']
        print(title)
        jw_id = movies_db.loc[idx, 'jw_id']
        rt_score = movies_db.loc[idx, 'rt_score']
        prev_streams = movies_db.loc[idx, 'streams']
        prev_genres = movies_db.loc[idx, 'genres']
        if not not jw_id and isinstance(jw_id, float) and not np.isnan(jw_id):
            jw_id, rt_score, streams, gs = getJustWatch(
                title, jw_id, rt_score, prev_streams, prev_genres
            )
            movies_db.at[idx, 'jw_id'] = jw_id
            if not np.isnan(rt_score):
                movies_db.at[idx, 'rt_score'] = rt_score
                if any(streams):
                    for s in streams:
                        if s not in prev_streams:
                            if "Netflix" in s and "Netflix" not in prev_streams:
                                prev_streams.append('Netflix')
                            else:
                                prev_streams.append(s)
                    if prev_streams is None:
                        prev_streams = []
                    prev_streams = [s for s in prev_streams if s in my_providers]
                    prev_streams = list(set(prev_streams))
                    movies_db.at[idx, 'streams'] = prev_streams
                else:
                    if 'Streaming' not in movies_db.loc[idx, 'queue']:
                        movies_db.at[idx, 'streams'] = []
                    else:
                        movies_db.loc[idx, 'streams'] = ['Netflix']

## combine new movies with previous DB
## save updated combined DB
new_movies = pd.DataFrame(movies)
out_movies = movies_db.append(new_movies, ignore_index = True)
if saved_movies is not None:
    saved_movies = pd.DataFrame(saved_movies)
    out_movies = out_movies.append(saved_movies, ignore_index = True)
if mylist_movies is not None:
    mylist_movies = pd.DataFrame(mylist_movies)
    out_movies = out_movies.append(mylist_movies, ignore_index = True)
if gallery_movies is not None:
    gallery_movies = pd.DataFrame(gallery_movies)
    out_movies = out_movies.append(gallery_movies, ignore_index = True)

with open('databases/movies_db.json', 'w') as outfile:
    json.dump(list(out_movies.T.to_dict().values()), outfile)

try:
    os.remove('new_movies.json')
except OSError:
    pass
