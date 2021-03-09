import os
import json
import pytz
import twarc
import dotenv
import logging
import datetime
import threading

dotenv.load_dotenv()
consumer_key = os.environ.get('CONSUMER_KEY')
consumer_secret = os.environ.get('CONSUMER_SECRET')
bearer_token = os.environ.get("BEARER_TOKEN")
access_token = os.environ.get('ACCESS_TOKEN')
access_token_secret = os.environ.get('ACCESS_TOKEN_SECRET')

logging.basicConfig(filename="test.log", level=logging.INFO)

T = None

def test_constructor():
    global T
    T = twarc.Twarc2(consumer_key, consumer_secret, bearer_token, access_token,
            access_token_secret)
    assert T.bearer_token


def test_sample():
    count = 0

    # event to tell the filter stream to close
    event = threading.Event()

    for result in T.sample(event=event):
        assert int(result["data"]["id"])

        # users are passed by reference an dincluded as includes
        user_id = result["data"]["author_id"]
        assert len(pick_id(user_id, result["includes"]["users"])) == 1

        count += 1
        if count > 10:
            # close the sample
            event.set()

    assert count == 11


def test_search():

    found_tweets = 0
    pages = 0

    for response_page in T.search("#auspol"):
        pages += 1
        tweets = response_page["data"]
        found_tweets += len(tweets)

        if pages == 3:
            break

    assert 200 <= found_tweets <= 300


def test_search_times():
    found = False
    now = datetime.datetime.now(tz=pytz.timezone('Australia/Melbourne'))
    # twitter api doesn't resolve microseconds so strip them for comparison
    now = now.replace(microsecond=0)
    end = now - datetime.timedelta(seconds=60)
    start = now - datetime.timedelta(seconds=61)

    for response_page in T.search("tweet", start_time=start, 
            end_time=end):
        for tweet in response_page["data"]:
            found = True
            # convert created_at to datetime with utc timezone
            dt = tweet['created_at'].strip('Z')
            dt = datetime.datetime.fromisoformat(dt)
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            assert dt >= start 
            assert dt <= end

    assert found


def test_user_ids_lookup():
    users_found = 0
    users_not_found = 0

    for response in T.user_lookup(range(1, 1000)):

        for profile in response["data"]:
            users_found += 1

        for error in response["errors"]:
            # Note that errors includes lookup of contained entitites within a
            # tweet, so a pinned tweet that doesn't exist anymore results in an
            # additional error entry, even if the profile is present.
            if error["resource_type"] == "user":
                users_not_found += 1

    assert users_found >= 1
    assert users_found + users_not_found == 999


def test_usernames_lookup():
    users_found = 0
    usernames = ['jack', 'barackobama', 'rihanna']
    for response in T.user_lookup(usernames, usernames=True):
        for profile in response["data"]:
            users_found += 1
    assert users_found == 3


def test_tweet_lookup():

    tweets_found = 0
    tweets_not_found = 0

    for response in T.tweet_lookup(range(1000, 2000)):

        for tweet in response["data"]:
            tweets_found += 1

        for error in response["errors"]:
            # Note that errors includes lookup of contained entitites within a
            # tweet, so a pinned tweet that doesn't exist anymore results in an
            # additional error entry, even if the profile is present.
            if error["resource_type"] == "tweet":
                tweets_not_found += 1
                
    assert tweets_found >= 1
    assert tweets_found + tweets_not_found == 1000


def test_stream():
    # remove any active stream rules
    rules = T.get_stream_rules()
    if 'data' in rules and len(rules['data']) > 0:
        rule_ids = [r['id'] for r in rules['data']]
        T.delete_stream_rule_ids(rule_ids)

    # make sure they are empty
    rules = T.get_stream_rules()
    assert 'data' not in rules

    # add two rules
    rules = T.add_stream_rules([
        {"value": "hey", "tag": "twarc-test"},
        {"value": "joe", "tag": "twarc-test"}
    ])
    assert len(rules['data']) == 2

    # make sure they are there
    rules = T.get_stream_rules()
    assert len(rules['data']) == 2
    assert rules['data'][0]["id"]
    assert rules['data'][0]["value"] == "hey"
    assert rules['data'][0]["tag"] == "twarc-test"
    assert rules['data'][1]["id"]
    assert rules['data'][1]["value"] == "joe"
    assert rules['data'][1]["tag"] == "twarc-test"

    # collect some data
    count = 0
    event = threading.Event()
    for result in T.stream(event=event):
        count += 1
        assert result['data']['id']
        assert result['data']['text']
        assert len(result['matching_rules']) > 0
        for rule in result['matching_rules']:
            assert rule['id']
            assert rule['tag'] == 'twarc-test'
        if count > 25:
            event.set()
    assert count > 25 

    # delete the rules
    rule_ids = [r['id'] for r in rules['data']]
    T.delete_stream_rule_ids(rule_ids)

    # make sure they are gone
    rules = T.get_stream_rules()
    assert 'data' not in rules
    

def test_flattened():
    """
    This test uses the sample stream to test response flattening.  It will look
    at each tweet to find evidence that all the expansions have worked. Once it
    finds them all it stops. If it has listened to 5000 tweets and not found any
    of the expansions it stops and assumes that something is not right.  This
    5000 cutoff may need to be adjusted based on experience.
    """
    found_geo = False
    found_in_reply_to_user = False
    found_attachments_media = False
    found_attachments_polls = False
    found_entities_mentions = False
    found_referenced_tweets = False

    count = 0
    event = threading.Event()
    for result in T.sample(event=event):
        result = twarc.expansions.flatten(result)

        tweet = result["data"]
        assert "id" in tweet
        logging.info("got sample tweet #%s %s", count, tweet["id"])

        author_id = tweet["author_id"]
        assert "author" in tweet 
        assert result["data"]["author"]["id"] == author_id

        if "in_reply_to_user_id" in tweet:
            assert "in_reply_to_user" in tweet
            found_in_reply_to_user = True

        if "attachments" in tweet:
            if "media_keys" in tweet["attachments"]:
                assert "media" in tweet["attachments"]
                found_attachments_media = True
            if "poll_ids" in tweet["attachments"]:
                assert "poll" in tweet["attachments"]
                found_attachments_polls = True

        if "geo" in tweet:
            assert tweet["geo"]["place_id"]
            assert tweet["geo"]["place_id"] == tweet["geo"]["id"]
            found_geo = True

        if "entities" in tweet and "mentions" in tweet["entities"]:
            assert tweet["entities"]["mentions"][0]["username"]
            found_entities_mentions = True

        if "referenced_tweets" in tweet:
            assert tweet["referenced_tweets"][0]["id"]
            found_referenced_tweets = True

        count += 1
        if found_geo and found_in_reply_to_user and found_attachments_media \
                and found_attachments_polls and found_entities_mentions \
                and found_referenced_tweets:
            logging.info("found all expansions!")
            event.set()
        elif count > 10000:
            logging.info("didn't find all expansions in 5000 tweets")
            event.set()

    assert found_geo, "found geo" 
    assert found_in_reply_to_user, "found in_reply_to_user"
    assert found_attachments_media, "found media"
    assert found_attachments_polls, "found polls"
    assert found_entities_mentions, "found mentions"
    assert found_referenced_tweets, "found referenced tweets"


def pick_id(id, objects):
    """pick an object out of a list of objects using its id
    """
    return list(filter(lambda o: o["id"] == id, objects))
