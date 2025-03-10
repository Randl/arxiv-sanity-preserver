"""
Queries arxiv API and downloads papers (the query is a parameter).
The script is intended to enrich an existing database pickle (by default db.p),
so this file will be loaded first, and then new results will be added to it.
"""

import argparse
import pickle
import random
import time
import urllib.request

import feedparser

from utils import Config, safe_pickle_dump


def encode_feedparser_dict(d):
    """
    helper function to get rid of feedparser bs with a deep copy.
    I hate when libs wrap simple things in their own classes.
    """
    if isinstance(d, feedparser.FeedParserDict) or isinstance(d, dict):
        j = {}
        for k in d.keys():
            j[k] = encode_feedparser_dict(d[k])
        return j
    elif isinstance(d, list):
        l = []
        for k in d:
            l.append(encode_feedparser_dict(k))
        return l
    else:
        return d


def parse_arxiv_url(url):
    """
    examples is http://arxiv.org/abs/1512.08756v2
    we want to extract the raw id and the version
    """
    ix = url.rfind('/')
    idversion = url[ix + 1:]  # extract just the id (and the version)
    parts = idversion.split('v')
    assert len(parts) == 2, 'error parsing url ' + url
    return parts[0], int(parts[1])


def fetch_api(args, db):
    # misc hardcoded variables
    base_url = 'http://export.arxiv.org/api/query?'  # base api query url
    print('Searching arXiv for %s' % (args.search_query,))

    num_added_total = 0
    for i in range(args.start_index, args.max_index, args.results_per_iteration):

        print("Results %i - %i" % (i, i + args.results_per_iteration))
        query = 'search_query=%s&sortBy=lastUpdatedDate&start=%i&max_results=%i' % (args.search_query,
                                                                                    i, args.results_per_iteration)
        with urllib.request.urlopen(base_url + query) as url:
            response = url.read()
        parse = feedparser.parse(response)
        num_added = 0
        num_skipped = 0
        for e in parse.entries:

            j = encode_feedparser_dict(e)

            # extract just the raw arxiv id and version for this paper
            rawid, version = parse_arxiv_url(j['id'])
            j['_rawid'] = rawid
            j['_version'] = version

            # add to our database if we didn't have it before, or if this is a new version
            if not rawid in db or j['_version'] > db[rawid]['_version']:
                db[rawid] = j
                print('Updated %s added %s' % (j['updated'].encode('utf-8'), j['title'].encode('utf-8')))
                num_added += 1
                num_added_total += 1
            else:
                num_skipped += 1

        # print some information
        print('Added %d papers, already had %d.' % (num_added, num_skipped))

        if len(parse.entries) == 0:
            print('Received no results from arxiv. Rate limiting? Exiting. Restart later maybe.')
            print(response)
            break

        if num_added == 0 and args.break_on_no_added == 1:
            print('No new papers were added. Assuming no new papers exist. Exiting.')
            break

        print('Sleeping for %i seconds' % (args.wait_time,))
        time.sleep(args.wait_time + random.uniform(0, 3))

    return db, num_added_total


def fetch_kaggle(args, db):
    import kaggle
    import jsonlines

    cat_set = set(args.categories)

    print('Authenticating at kaggle')
    kaggle.api.authenticate()
    print('Downloading kaggle data')
    kaggle.api.dataset_download_files('Cornell-University/arxiv', path='./kaggle', unzip=True)
    print('Downloaded kaggle data')
    num_added_total = 0
    num_skipped_total = 0
    with jsonlines.open('kaggle/arxiv-metadata-oai-snapshot.json') as reader:
        for paper in reader:
            categories = set(paper['categories'].split())
            if args.categories is None or len(categories.intersection(cat_set)) > 0:
                paper['_version'] = len(paper['versions'])
                paper['updated'] = paper['versions'][-1]['created']
                paper['published'] = paper['versions'][0]['created']
                paper['_authors'] = paper['authors']
                paper['authors'] = [{'name': " ".join([x[1], x[0]]).strip()} for x in paper['authors_parsed']]
                paper['links'] = [{'title': 'pdf',
                                   'href': 'http://arxiv.org/pdf/{}{}'.format(paper['id'],
                                                                              paper['versions'][-1]['version']),
                                   'rel': 'related', 'type': 'application/pdf'}]
                paper['link'] = 'http://arxiv.org/abs/{}{}'.format(paper['id'], paper['versions'][-1]['version'])
                rawid = paper['_rawid'] = paper['id']
                paper['tags'] = [{'term': x} for x in categories]
                paper['arxiv_primary_category'] = paper['tags'][0]
                paper['summary'] = paper['abstract']

                # add to our database if we didn't have it before, or if this is a new version
                if not rawid in db or paper['_version'] > db[rawid]['_version']:
                    db[rawid] = paper
                    print('Updated %s added %s' % (paper['updated'].encode('utf-8'), paper['title'].encode('utf-8')))
                    num_added_total += 1
                else:
                    num_skipped_total += 1

    print('Added %d papers, already had %d.' % (num_added_total, num_skipped_total))
    return db, num_added_total


if __name__ == "__main__":

    # parse input arguments
    parser = argparse.ArgumentParser()

    parser.add_argument('--categories', type=str,
                        default=['cs.CV', 'cs.AI', 'cs.LG', 'cs.CL', 'cs.NE', 'stat.ML', 'cond-mat.dis-nn'],
                        help='categories to search for')
    parser.add_argument('--search-query', type=str,
                        default='cat:cs.CV+OR+cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL+OR+cat:cs.NE+OR+cat:stat.ML+OR+cat:cond-mat.dis-nn',
                        help='query used for arxiv API. See http://arxiv.org/help/api/user-manual#detailed_examples')
    parser.add_argument('--start-index', type=int, default=0, help='0 = most recent API result')
    parser.add_argument('--max-index', type=int, default=10000, help='upper bound on paper index we will fetch')
    parser.add_argument('--kaggle', dest='kaggle', action='store_true', help='use kaggle data')
    parser.add_argument('--results-per-iteration', type=int, default=100, help='passed to arxiv API')
    parser.add_argument('--wait-time', type=float, default=5.0,
                        help='lets be gentle to arxiv API (in number of seconds)')
    parser.add_argument('--break-on-no-added', type=int, default=1,
                        help='break out early if all returned query papers are already in db? 1=yes, 0=no')
    args = parser.parse_args()

    #args.search_query = '%28' + '+OR+'.join(args.categories) + '%29' + args.search_query
    # lets load the existing database to memory
    try:
        db = pickle.load(open(Config.db_path, 'rb'))
    except Exception as e:
        print('error loading existing database:')
        print(e)
        print('starting from an empty database')
        db = {}

    # -----------------------------------------------------------------------------
    # main loop where we fetch the new results
    print('database has %d entries at start' % (len(db),))

    if args.kaggle:
        db, num_added_total = fetch_kaggle(args, db)
    else:
        db, num_added_total = fetch_api(args, db)

    if num_added_total > 0:
        print('Saving database with %d papers to %s' % (len(db), Config.db_path))
        safe_pickle_dump(db, Config.db_path)
